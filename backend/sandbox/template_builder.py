from dotenv import load_dotenv
from e2b import Template
from e2b.template.logger import default_build_logger

load_dotenv()


def build_e2b_template(name="jupyter-server"):
    template = Template().from_image("mikelarg/code-interpreter:0.0.7")
    Template.build(
        template,
        alias=name,
        cpu_count=1,
        memory_mb=1024,
        on_build_logs=default_build_logger(),
    )


if __name__ == "__main__":
    build_e2b_template()
