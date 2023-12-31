import typing
import pandas as pd
import os
from datetime import datetime
import json
import re, shutil
from .utils import create_folder_if_not, get_directory_structure
from ..settings import TMP_BASE_PATH


def format_df_columns(df: pd.DataFrame, column_metadata):
    # update column names with user specified column names

    user_specified_column_name = {
        old_column: mapping["updated_col_name"]
        for old_column, mapping in column_metadata.items()
    }

    df = df.rename(columns=user_specified_column_name)

    def clean_column_name(column_name):
        # Convert to lowercase
        column_name = column_name.lower()
        # Remove special characters (replace with '')
        column_name = re.sub(r"[^a-zA-Z0-9]", " ", column_name)
        column_name = column_name.strip()
        column_name = re.sub(r" {2,}", " ", column_name)
        # Replace spaces with underscores
        column_name = column_name.replace(" ", "_")
        return column_name

    old_column_mapping = {col: clean_column_name(col) for col in df.columns}
    df.columns = [clean_column_name(col) for col in df.columns]
    return df, old_column_mapping


def guess_metrics_and_columns(token: str, filename: str):
    file_path = os.path.join(TMP_BASE_PATH, token, filename)
    df = pd.read_csv(file_path)
    column_type_dict = dict()

    for column in df.columns:
        if df[column].dtype == "int":
            column_type_dict[df[column].name] = {
                "updated_col_name": df[column].name,
                "metric": True,
                "dimension": False,
            }
        else:
            column_type_dict[df[column].name] = {
                "updated_col_name": df[column].name,
                "metric": False,
                "dimension": True,
            }
    return column_type_dict


def generate_ingest_files(
    token: str, column_metadata: typing.Dict, program_name: str, program_desc: str
):
    folder_path = os.path.join(TMP_BASE_PATH, token)
    file_path = os.path.join(
        folder_path,
        [file for file in os.listdir(folder_path) if file.endswith(".csv")][0],
    )
    df = pd.read_csv(file_path)

    df, column_mapping = format_df_columns(df, column_metadata)

    metrics, dimensions = [], []

    for cols in column_metadata:
        updated_col_name = column_metadata[cols]["updated_col_name"]
        if column_metadata[cols]["metric"]:
            metrics.append(column_mapping[updated_col_name])
        else:
            dimensions.append(column_mapping[updated_col_name])

    ingest_folder_path = os.path.join(folder_path, "ingest")

    write_dimensions_to_ingest_folder(df, dimensions, ingest_folder_path)
    write_events_to_ingest_folder(
        df, dimensions, metrics, program_name, ingest_folder_path
    )
    write_config_to_ingest_folder(program_name, program_desc, ingest_folder_path)

    return {"dimension": dimensions, "metrics": metrics}


def write_dimensions_to_ingest_folder(
    df: pd.DataFrame, dimensions: typing.Iterable, ingest_folder_path: str
):
    dimensions_base_path = os.path.join(ingest_folder_path, "dimensions")
    create_folder_if_not(dimensions_base_path)

    for dimension in dimensions:
        dimension_grammar_data = f"""PK,Index
string,string
{dimension}_id,{dimension}"""
        with open(
            os.path.join(dimensions_base_path, f"{dimension}-dimension.grammar.csv"),
            "w",
        ) as f:
            f.write(dimension_grammar_data)
        column_df = pd.DataFrame(df[dimension].drop_duplicates(keep="first"))
        column_df.insert(
            loc=0, column=f"{dimension}_id", value=range(1, len(column_df) + 1)
        )
        column_df.to_csv(
            os.path.join(dimensions_base_path, f"{dimension}-dimension.data.csv"),
            index=False,
        )


def write_events_to_ingest_folder(
    df: pd.DataFrame, dimensions, metrics, program_name, ingest_folder_path
):
    events_base_path = os.path.join(ingest_folder_path, "programs", program_name)
    create_folder_if_not(events_base_path)

    for metric in metrics:
        with open(
            os.path.join(events_base_path, f"{metric}-event.grammar.csv"), "w"
        ) as f:
            f.write("," + ",".join(dimensions) + "," + "\n")
            f.write("," + ",".join(dimensions) + "," + "\n")
            f.write("date," + "string," * (len(dimensions)) + "integer" "\n")
            f.write("date," + ",".join(dimensions) + f",{metric}" + "\n")
            f.write(
                "timeDimension," + "dimension," * (len(dimensions)) + "metric" + "\n"
            )
        headers = dimensions + [metric]
        event_df = pd.DataFrame(df[headers])
        event_df.insert(
            loc=0, column=f"date", value=datetime.today().strftime("%d/%m/%y")
        )
        event_df.to_csv(
            os.path.join(events_base_path, f"{metric}-event.data.csv"), index=False
        )


def write_config_to_ingest_folder(
    program_name, program_description, ingest_folder_path
):
    config_template = {
        "globals": {"onlyCreateWhitelisted": "true"},
        "dimensions": {
            "namespace": "dimensions",
            "fileNameFormat": "${dimensionName}.${index}.dimensions.data.csv",
            "input": {"files": "./ingest/dimensions"},
        },
        "programs": [
            {
                "name": program_name,
                "namespace": program_name,
                "description": program_description,
                "shouldIngestToDB": "true",
                "input": {"files": f"./ingest/programs/{program_name}"},
                "./output": {"location": f"./output/programs/{program_name}"},
                "dimensions": {"whitelisted": [], "blacklisted": []},
            }
        ],
    }

    config_json = json.dumps(config_template, indent=4)

    with open(os.path.join(ingest_folder_path, "config.json"), "w") as f:
        f.write(config_json)


def get_dimensions(token: str):
    folder_path = os.path.join(TMP_BASE_PATH, token, "ingest/", "dimensions")
    return get_directory_structure(folder_path)


def get_ingest_folder_path(token):
    program_folder_path = os.path.join(TMP_BASE_PATH, token, "ingest/programs")
    program_name = os.listdir(program_folder_path)[0]
    folder_path = os.path.join(program_folder_path, program_name)
    return folder_path


def get_events(token: str):
    return get_directory_structure(get_ingest_folder_path(token))


def download_ingest_folder(token: str):
    ingest_folder_path = os.path.join(TMP_BASE_PATH, token, "ingest")
    zip_location_path = os.path.join(TMP_BASE_PATH, token, "cqube-ingest")

    return shutil.make_archive(zip_location_path, "zip", ingest_folder_path)


def fetch_file_content(token: str, filename: str):
    if filename.endswith("event.data.csv") or filename.endswith("event.grammar.csv"):
        file_path = os.path.join(get_ingest_folder_path(token), filename)
    elif filename.endswith("dimension.data.csv") or filename.endswith(
        "dimension.grammar.csv"
    ):
        file_path = os.path.join(TMP_BASE_PATH, token, "ingest", "dimensions", filename)

    else:
        return None
    if not os.path.exists(file_path):
        return None
    df = pd.read_csv(file_path)
    json_response = df.head().to_json(orient="records")
    return json_response
