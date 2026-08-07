"""How specification field types map onto Python and SQLAlchemy types."""

from vibestack.spec import FieldType

# The SQLAlchemy column type written into a model, including any length.
SQLALCHEMY_COLUMN_TYPES = {
    FieldType.INTEGER: "Integer",
    FieldType.STRING: "String(255)",
    FieldType.BOOLEAN: "Boolean",
    FieldType.DATETIME: "DateTime",
    FieldType.TEXT: "Text",
    FieldType.FLOAT: "Float",
}

# The bare name that must be imported from sqlalchemy for each column type.
SQLALCHEMY_IMPORT_NAMES = {
    FieldType.INTEGER: "Integer",
    FieldType.STRING: "String",
    FieldType.BOOLEAN: "Boolean",
    FieldType.DATETIME: "DateTime",
    FieldType.TEXT: "Text",
    FieldType.FLOAT: "Float",
}

# The Python annotation used in Pydantic schemas.
PYTHON_TYPE_NAMES = {
    FieldType.INTEGER: "int",
    FieldType.STRING: "str",
    FieldType.BOOLEAN: "bool",
    FieldType.DATETIME: "datetime",
    FieldType.TEXT: "str",
    FieldType.FLOAT: "float",
}
