import json
import csv
import io
import argparse
from typing import Any

import modal
from fastapi import Response, Request

app = modal.App("json-to-csv")

image = modal.Image.debian_slim().pip_install("fastapi")
REMOTE_OPTIONS = {
    "image": image,
    "min_containers": 1,
    "buffer_containers": 1,
    "scaledown_window": 300,
}


class InvalidJsonInput(ValueError):
    pass


def flatten_json(obj: Any, parent_key: str = "", sep: str = ".") -> dict[str, Any]:
    items: dict[str, Any] = {}

    def add_item(key: str, value: Any) -> None:
        if key in items:
            raise InvalidJsonInput(f"Colisao de chave ao achatar JSON: {key}")
        items[key] = value

    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, (dict, list)):
                for nested_key, nested_value in flatten_json(
                    v, new_key, sep=sep
                ).items():
                    add_item(nested_key, nested_value)
            else:
                add_item(new_key, v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_key = f"{parent_key}{sep}{i}" if parent_key else str(i)
            if isinstance(v, (dict, list)):
                for nested_key, nested_value in flatten_json(
                    v, new_key, sep=sep
                ).items():
                    add_item(nested_key, nested_value)
            else:
                add_item(new_key, v)
    else:
        add_item(parent_key, obj)
    return items


def json_to_csv(json_str: str) -> str:
    parsed = json.loads(json_str)
    if isinstance(parsed, dict):
        parsed = [parsed]
    elif not isinstance(parsed, list):
        raise InvalidJsonInput("O JSON deve ser um objeto ou uma lista de objetos")

    rows = [flatten_json(item) for item in parsed]
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row:
            if k not in seen:
                fieldnames.append(k)
                seen.add(k)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    return output.getvalue()


@app.function(**REMOTE_OPTIONS)
@modal.fastapi_endpoint(method="POST", docs=True)
async def converter(request: Request):
    body = await request.body()
    if not body:
        return Response(
            json.dumps({"error": "Envie o JSON no corpo da requisição"}),
            media_type="application/json",
            status_code=400,
        )
    try:
        csv_result = json_to_csv(body.decode("utf-8"))
        return Response(
            content=csv_result,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=output.csv"},
        )
    except (json.JSONDecodeError, UnicodeDecodeError, InvalidJsonInput) as e:
        return Response(
            json.dumps({"error": str(e)}),
            media_type="application/json",
            status_code=400,
        )
    except Exception as e:
        return Response(
            json.dumps({"error": str(e)}),
            media_type="application/json",
            status_code=500,
        )


@app.function(**REMOTE_OPTIONS)
def convert_large(json_str: str) -> str:
    return json_to_csv(json_str)


def convert_file(
    file_path: str = "example_input.json",
    output: str = "output.csv",
    remote: bool = False,
) -> None:
    with open(file_path, "r", encoding="utf-8") as f:
        json_str = f.read()

    csv_result = convert_large.remote(json_str) if remote else json_to_csv(json_str)

    with open(output, "w", encoding="utf-8", newline="") as f:
        f.write(csv_result)
    print(f"CSV salvo em: {output}")


@app.local_entrypoint()
def main(
    file_path: str = "example_input.json",
    output: str = "output.csv",
    remote: bool = False,
):
    convert_file(file_path, output, remote)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Converte JSON para CSV")
    parser.add_argument("--file-path", default="example_input.json")
    parser.add_argument("--output", default="output.csv")
    parser.add_argument("--remote", action="store_true")
    args = parser.parse_args()
    if args.remote:
        parser.error("use 'modal run main.py --remote' para executar remotamente")

    convert_file(args.file_path, args.output)
