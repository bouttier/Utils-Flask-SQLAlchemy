"""
  Serialize function for SQLAlchemy models
"""
import uuid
import datetime

from inspect import signature
from warnings import warn
from collections import defaultdict
from itertools import chain
from uuid import UUID

from flask.json import JSONEncoder
from sqlalchemy.orm import ColumnProperty
from sqlalchemy import inspect


"""
    List of data type who need a particular serialization
    @TODO MISSING FLOAT
"""
SERIALIZERS = {
    "date": lambda x: str(x) if x else None,
    "datetime": lambda x: str(x) if x else None,
    "time": lambda x: str(x) if x else None,
    "timestamp": lambda x: str(x) if x else None,
    "uuid": lambda x: str(x) if x else None,
    "numeric": lambda x: str(x) if x else None,
}

def get_serializable_decorator(fields=[], exclude=[]):
    default_fields = fields
    default_exclude = exclude

    _columns = None
    _relationships = None
    _test = None

    def _serializable(cls):
        """
            Décorateur de classe pour les DB.Models
            Permet de rajouter la fonction as_dict
            qui est basée sur le mapping SQLAlchemy
        """

        def get_cls_db_columns():
            """
                Liste des propriétés sérialisables de la classe
                associées à leur sérializer en fonction de leur type
            """
            cls_db_columns = []
            for prop in cls.__mapper__.column_attrs:
                if isinstance(prop, ColumnProperty):  # and len(prop.columns) == 1:
                    # -1 : si on est dans le cas d'un heritage on recupere le dernier element de prop
                    # qui correspond à la derniere redefinition de cette colonne
                    assert(len(prop.columns) == 1)
                    db_col = prop.columns[-1]
                    # HACK
                    #  -> Récupération du nom de l'attribut sans la classe
                    name = str(prop).split('.', 1)[1]
                    if db_col.type.__class__.__name__ == 'Geometry':
                        continue
                    if name in exclude:
                        continue
                    cls_db_columns.append((
                        name,
                        SERIALIZERS.get(
                            db_col.type.__class__.__name__.lower(),
                            lambda x: x
                        )
                    ))
            """
                Liste des propriétés synonymes
                sérialisables de la classe
                associées à leur sérializer en fonction de leur type
            """
            for syn in cls.__mapper__.synonyms:
                col = cls.__mapper__.c[syn.name]
                # if column type is geometry pass
                if col.type.__class__.__name__ == 'Geometry':
                    pass

                # else add synonyms in columns properties
                cls_db_columns.append((
                    syn.key,
                    SERIALIZERS.get(
                        col.type.__class__.__name__.lower(),
                        lambda x: x
                    )
                ))
            return cls_db_columns

        def get_cls_db_relationships():
            """
                Liste des propriétés de type relationship
                uselist permet de savoir si c'est une collection de sous objet
                sa valeur est déduite du type de relation
                (OneToMany, ManyToOne ou ManyToMany)
            """
            return [
                (
                    db_rel.key,
                    db_rel.uselist,
                    getattr(cls, db_rel.key).mapper.class_
                ) for db_rel in cls.__mapper__.relationships
            ]

        def serializefn(self, recursif=False, columns=[], relationships=[],
                        fields=None, exclude=None, depth=None, _excluded_mappers=[]):
            """
            Méthode qui renvoie les données de l'objet sous la forme d'un dict

            Parameters
            ----------
                fields: liste
                    Liste des champs (colonne native ou relationship) à prendre en compte, e.g. :
                        fields=['column1', 'column2', 'child1', 'child2']
                    Si fields n’est pas spécifié, l’ensemble des colonnes sont sélectionnées.
                    Les relationships doivent être explicitement spécifiées dans fields pour être
                    prise en compte en plus des propres colonnes de l’objet, e.g. :
                        fields=['child']
                    Il est également possible de spécifier les champs d’une relationship
                    à prendre en compte, sans limite de profondeur, avec un '.' :
                        fields=['child.column1', 'child.otherchild.column2']
                exclude: list
                    Liste de champs à exclure.
                    Les exclusions s’appliquent après la sélection des champs avec fields.
                    Il est également possible d’utiliser la notation avec un '.', e.g. :
                        fields=['child'],exclude=['child.column2']

                Les arguments ci-après sont dépréciés en faveur de fields et exclude.

                recursif: boolean
                        Spécifie si on veut que les sous-objets (relationship)
                depth: entier
                    spécifie le niveau de niveau de récursion:
                        0 juste l'objet
                        1 l'objet et ses sous-objets
                        2 ...
                    si depth est spécifié :
                        recursif prend la valeur True
                    si depth n'est pas spécifié et recursif est à True :
                        il n'y a pas de limite à la récursivité
                columns: liste
                    liste des colonnes qui doivent être prises en compte
                relationships: liste
                    liste des relationships qui doivent être prise en compte
            """

            mapper = inspect(cls)
            

            if fields is None:
                fields = default_fields
            if exclude is None:
                exclude = default_exclude

            if columns:
                warn("'columns' argument is deprecated. Please add columns to serialize "
                     "directly in 'fields' argument.", DeprecationWarning)
                fields = chain(fields, columns)
            if relationships:
                warn("'relationships' argument is deprecated. Please add relationships to serialize "
                     "directly in 'fields' argument.", DeprecationWarning)
                fields = chain(fields, relationships)

            if depth:
                recursif = True
            if recursif:
                warn("'recursif' argument is deprecated. Please add relationships to serialize "
                     "directly in 'fields' argument.", DeprecationWarning)
                _excluded_mappers = _excluded_mappers + [ mapper ]
                if depth is None or depth > 0:
                    fields = chain(fields, [ rel.key for rel in mapper.relationships
                                             if rel.key not in fields
                                             and rel.mapper not in _excluded_mappers ])
                    if depth:
                        depth -= 1

            fields = list(fields)
            exclude = list(exclude)

            # take 'a' instead of 'a.b'
            firstlevel_fields = [ rel.split('.')[0] for rel in fields ]

            for field in set([ f for f in fields if '.' not in f ]) \
                    - { col.name for col in mapper.columns } \
                    - { rel.key for rel in mapper.relationships }:
                raise Exception(f"Field '{field}' does not exist on {cls}.")
            for field in set([ f.split('.')[0] for f in fields if '.' in f ]) \
                    - { rel.key for rel in mapper.relationships }:
                raise Exception(f"Relationship '{field}' does not exist on {cls}.")


            _columns = { key: col
                         for key, col in mapper.columns.items()
                         if key in fields }
            _relationships = { key: rel
                               for key, rel in mapper.relationships.items()
                               if key in firstlevel_fields }
            if not _columns:
                _columns = mapper.columns
            if exclude:
                _columns = { key: col
                             for key, col in _columns.items()
                             if key not in exclude }
                _relationships = { key: rel
                                   for key, rel in _relationships.items()
                                   if key not in exclude }

            serialize_kwargs = {
                'recursif': recursif,
                'depth': depth,
                '_excluded_mappers': _excluded_mappers,
            }

            data = {}
            for key, col in _columns.items():
                data[key] = getattr(self, key)
            for key, rel in _relationships.items():
                kwargs = serialize_kwargs.copy()
                _fields = [ field.split('.', 1)[1]
                            for field in fields
                            if field.startswith(f'{key}.') ]
                kwargs['fields'] = _fields or None
                _exclude = [ field.split('.', 1)[1]
                             for field in exclude
                             if field.startswith(f'{key}.') ]
                kwargs['exclude'] = _exclude or None
                if rel.uselist:
                    data[key] = [ o.as_dict(**kwargs) for o in getattr(self, key) ]
                else:
                    rel_object = getattr(self, rel.key)
                    if rel_object:
                        data[rel.key] = rel_object.as_dict(**kwargs)
                    else:
                        data[rel.key] = None
            return data


        def populatefn(self, dict_in, recursif=False):
            '''
            Méthode qui initie les valeurs de l'objet à partir d'un dictionnaire

            Parameters
            ----------
                dict_in : dictionnaire contenant les valeurs à passer à l'objet
                recursif: si on renseigne les relationships

            '''

            cls_db_columns_key = list(map(lambda x: x[0], get_cls_db_columns()))

            # populate cls_db_columns
            for key in dict_in:
                if key in cls_db_columns_key:
                    setattr(self, key, dict_in[key])

            # si non recursif, on ne traite pas les relationship
            if not recursif:
                return self

            # gestion des relationships
            frel = get_cls_db_relationships()

            for (rel, uselist, Model) in frel:

                if rel not in dict_in:
                    continue

                values = dict_in.get(rel)
                if not values:
                    # check if None or {}
                    setattr(self, rel, [] if uselist else None)
                    continue

                # pour pouvoir traiter les cas uselist et not uselist de la même manière
                if not uselist:
                    values = [values]

                # get id_field_name
                id_field_name = inspect(Model).primary_key[0].name
                # si on a pas une liste de dictionaires
                # -> on suppose qu'on a une liste d'id
                # test sur le premier element de la liste
                # on cree une liste [ ... { <id_field_name>: id_value } ... ]
                if not isinstance(values[0], dict):
                    values_inter = []
                    for id_value in values:
                        data = {}
                        data[id_field_name] = id_value
                        values_inter.append(data)
                    values = values_inter



                # preload with id
                # pour faire une seule requête
                ids = filter(
                    lambda x: x,
                    map(
                        lambda x: x.get(id_field_name),
                        values
                    )
                )
                preload_res_with_ids = (
                    Model.query
                    .filter(getattr(Model, id_field_name).in_(ids))
                    .all()
                )

                # resul
                v_obj = []

                for data in values:

                    id_value = data.get(id_field_name)

                    # si id_value est null
                    # creation -> on supprime id_value
                    if not id_value:
                        data.pop(id_field_name)

                    res = (
                        # si on a une id -> on recupère dans la liste preload_res_with_ids
                        # TODO trouver un find plus propre ?
                        list(
                            filter(
                                lambda x: getattr(x, id_field_name) == id_value,
                                preload_res_with_ids
                            )
                        )[0]
                        if id_value and len(preload_res_with_ids)
                        # sinon on cree une nouvelle instance
                        else Model()
                    )
                    if hasattr(res, 'from_dict'):
                        res.from_dict(data, recursif)

                    v_obj.append(res)

                # attribution de la relation
                # si uselist est à false -> on prend le premier de la liste
                setattr(
                    self,
                    rel,
                    v_obj if uselist else v_obj[0]
                )

            return self

        if hasattr(cls, 'as_dict'):
            # the Model has a as_dict(self, data) method, which expects serialized data as argument
            if len(signature(cls.as_dict).parameters) == 2:
                userfn = cls.as_dict
                def chainedserializefn(self, *args, **kwargs):
                    return userfn(self, serializefn(self, *args, **kwargs))
                cls.as_dict = chainedserializefn
            # the Model has its own as_dict method, which will call super().as_dict() it-self
            elif 'as_dict' in vars(cls):
                pass
            # the Model has a as_dict method inherited, we replace-it with the serializer which will take child fields into account
            else:
                cls.as_dict = serializefn
        else:
            cls.as_dict = serializefn
        cls.from_dict = populatefn

        return cls

    return _serializable


def serializable(*args, **kwargs):
    if not kwargs and len(args) == 1 and isinstance(args[0], type):  # e.g. @serializable
        return get_serializable_decorator()(args[0])
    else:
        return get_serializable_decorator(*args, **kwargs)  # e.g. @serializable(exclude=['field'])


class CustomJSONEncoder(JSONEncoder):
    def default(self, o):
        try:
            if isinstance(o, datetime.time):
                return str(o) if o is not None else None
        except TypeError:
            pass
        return JSONEncoder.default(self, o)
