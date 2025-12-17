from genson import SchemaBuilder


def build_schema_from_json(data):
    schema = SchemaBuilder()
    schema.add_object(obj=data)
    return schema.to_schema()
