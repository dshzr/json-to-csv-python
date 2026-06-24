import json
import csv
import io
from typing import Any

import modal
from fastapi import Response, Request

app = modal.App("json-to-csv")

image = modal.Image.debian_slim().pip_install("fastapi[standard]")


def flatten_json(obj: Any, parent_key: str = "", sep: str = ".") -> dict[str, Any]:
    items: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, (dict, list)):
                items.extend(flatten_json(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_key = f"{parent_key}{sep}{i}" if parent_key else str(i)
            if isinstance(v, (dict, list)):
                items.extend(flatten_json(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
    else:
        items.append((parent_key, obj))
    return dict(items)


@app.cls(image=image)
class JsonToCsv:
    @modal.method()
    def convert(self, json_str: str) -> str:
        parsed = json.loads(json_str)
        if isinstance(parsed, dict):
            parsed = [parsed]

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


@app.function(image=image)
@modal.fastapi_endpoint(method="POST", docs=True)
async def converter(request: Request):
    body = await request.body()
    if not body:
        return Response(
            json.dumps({"error": "Envie o JSON no corpo da requisição"}),
            media_type="application/json",
        )
    try:
        conv = JsonToCsv()
        csv_result = conv.convert.remote(body.decode("utf-8"))
        return Response(
            content=csv_result,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=output.csv"},
        )
    except Exception as e:
        return Response(
            json.dumps({"error": str(e)}),
            media_type="application/json",
        )


@app.local_entrypoint()
def main(file_path: str = "example_input.json", output: str = "output.csv"):
    with open(file_path, "r") as f:
        json_str = f.read()

    converter = JsonToCsv()
    csv_result = converter.convert.remote(json_str)

    with open(output, "w") as f:
        f.write(csv_result)
    print(f"CSV salvo em: {output}")
