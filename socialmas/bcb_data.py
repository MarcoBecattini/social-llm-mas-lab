"""Access to the BigCodeBench-Instruct tasks used by the live mode, without redistributing them.

The dataset parquet (v0.1.4, Apache-2.0) is downloaded from Hugging Face on first use into the data directory,
verified against the SHA-256 the paper froze, and read with pyarrow. Only the tasks of the bundled pool manifests
are ever loaded into memory. Prompts, tests and canonical solutions never enter the repository or any download."""
import hashlib
import os
from pathlib import Path

DATASET_SPLIT = "v0.1.4"
DATASET_FILE = "v0.1.4-00000-of-00001.parquet"
DATASET_URL = "https://huggingface.co/datasets/bigcode/bigcodebench/resolve/main/data/v0.1.4-00000-of-00001.parquet"
DATASET_SHA256 = "d9a4965821c9507ebdfb551c288656b2d5fe553234f5183044333ca8a4018267"
SYSTEM_PROMPT = ("You are an expert Python programmer. Solve the task with one self-contained Python program. "
                 "Reply with exactly one ```python code block and nothing else. The block must start with the given "
                 "imports and function signature and must define the requested function completely.")
PROMPT_VERSION = "bcb-instruct-v1"


class DatasetError(RuntimeError):
    pass


def dataset_path(data_dir):
    return Path(data_dir) / "bcb" / DATASET_FILE


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dataset(data_dir, download=True, source=None):
    """Return the verified parquet path, downloading it (or copying `source`) when missing. Raises DatasetError."""
    target = dataset_path(data_dir)
    if target.exists() and sha256_file(target) == DATASET_SHA256:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    if source is not None:
        tmp.write_bytes(Path(source).read_bytes())
    elif download:
        import requests
        with requests.get(DATASET_URL, stream=True, timeout=(10, 120)) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    else:
        raise DatasetError("dataset not present and download disabled")
    if sha256_file(tmp) != DATASET_SHA256:
        tmp.unlink(missing_ok=True)
        raise DatasetError("downloaded dataset does not match the frozen SHA-256; refusing to use it")
    os.replace(tmp, target)
    return target


def load_tasks(parquet_path, task_ids):
    """{task_id: {instruct_prompt, code_prompt, canonical_solution, test, entry_point}} for the given ids only."""
    import pyarrow.parquet as pq
    table = pq.read_table(parquet_path, columns=["task_id", "instruct_prompt", "code_prompt", "canonical_solution", "test", "entry_point"])
    wanted = set(task_ids)
    out = {}
    for row in table.to_pylist():
        if row["task_id"] in wanted:
            out[row["task_id"]] = row
    missing = wanted - set(out)
    if missing:
        raise DatasetError(f"{len(missing)} pool tasks missing from the dataset, e.g. {sorted(missing)[:3]}")
    return out


def build_messages(task):
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": task["instruct_prompt"]}]


def extract_code(text):
    """First fenced python block; else first fenced block; else the raw text. Never raises."""
    import re
    fences = re.findall(r"```(?:python|py)?[ \t]*\n(.*?)```", text, re.S)
    return fences[0] if fences else text


def calibrated_solution(task, code):
    """Upstream 'calibrated' evaluation: prepend the code prompt with a pass body so imports are present."""
    return task["code_prompt"] + "\n    pass\n" + code
