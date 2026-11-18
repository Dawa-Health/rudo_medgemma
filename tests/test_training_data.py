"""
Integrity of the bundled knowledge-base modules in training/.
Each data module must load and expose a non-empty text block named after the file. This also
pulls training/cervical_cancer_data_bemba.py into the coverage report: main.py never imports it,
and because training/ has no __init__.py, coverage would otherwise leave it out silently.
"""
import glob
import importlib
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_MODULES = sorted(
    os.path.splitext(os.path.basename(p))[0]
    for p in glob.glob(os.path.join(ROOT, "training", "*_data*.py"))
    if os.path.basename(p) != "products_data.py"
)


def test_every_language_module_is_discovered():
    assert "cervical_cancer_data_bemba" in DATA_MODULES
    assert {f"pregnancy_data_{x}" for x in ("shona", "ndebele", "tonga", "chinyanja", "bemba", "lozi")} \
        <= set(DATA_MODULES)


@pytest.mark.parametrize("name", DATA_MODULES)
def test_data_module_exposes_text(name):
    mod = importlib.import_module(f"training.{name}")
    data = getattr(mod, name)
    # pregnancy modules are one string; cervical-cancer modules are tuples of FAQ strings.
    parts = (data,) if isinstance(data, str) else data
    assert isinstance(parts, tuple) and parts
    assert all(isinstance(p, str) for p in parts)
    assert len("".join(parts).strip()) > 200


def test_instructions_and_product_reexports():
    from training import instructions, product_images, products, products_data
    assert isinstance(instructions.instructions, str) and instructions.instructions.strip()
    assert isinstance(product_images.image_urls, dict)
    from products_data import products_by_category
    assert products.products is products_by_category
    assert products_data.products is products_by_category


# ─────────────── Gap Two: Bemba cervical-cancer data regression ───────────────
# Fix verified: training/cervical_cancer_data_bemba.py had a redundant first
# assignment (Q1-30) that was overwritten by the second (Q1-100).
# The correction removed the first block.  All Q1-100 content is preserved.


def test_bemba_cervical_data_single_assignment():
    """The file must have exactly one assignment, not a duplicated overwriting one.
    The previous audit reported two assignments with the second replacing the first.
    This test ensures the fix is not reverted."""
    import ast
    path = os.path.join(ROOT, "training", "cervical_cancer_data_bemba.py")
    tree = ast.parse(open(path).read())
    names = [n.targets[0].id for n in tree.body if isinstance(n, ast.Assign)]
    assert names.count("cervical_cancer_data_bemba") == 1, \
        f"Expected 1 assignment, found {names.count('cervical_cancer_data_bemba')}"


def test_bemba_cervical_data_contains_all_100_questions():
    """The corrected file must contain all 100 questions (Q1-Q100).
    Gap Two investigation confirmed the second block (Q1-100) was the complete
    superset and all Q1-30 of the first block were byte-identically contained."""
    mod = importlib.import_module("training.cervical_cancer_data_bemba")
    data = getattr(mod, "cervical_cancer_data_bemba")
    joined = "".join(data) if isinstance(data, tuple) else data
    for n in range(1, 101):
        assert f"Question {n}:" in joined, f"Question {n} is missing from Bemba cervical-cancer data"
    assert "Question 100:" in joined
    assert "Question 1:" in joined


def test_bemba_cervical_data_is_tuple_of_strings():
    """The data must be a tuple of non-empty strings (the training format)."""
    mod = importlib.import_module("training.cervical_cancer_data_bemba")
    data = getattr(mod, "cervical_cancer_data_bemba")
    assert isinstance(data, tuple), "cervical_cancer_data_bemba must be a tuple"
    assert len(data) > 90, f"Expected ~100 elements, got {len(data)}"
    assert all(isinstance(s, str) and s.strip() for s in data)


def test_bemba_cervical_data_no_duplicate_question_numbers():
    """Each question number must appear exactly once (no duplicate questions)."""
    import re
    mod = importlib.import_module("training.cervical_cancer_data_bemba")
    data = getattr(mod, "cervical_cancer_data_bemba")
    joined = "".join(data) if isinstance(data, tuple) else data
    nums = re.findall(r"Question (\d+):", joined)
    assert len(nums) == len(set(nums)), \
        f"Duplicate question numbers found: {nums}"


def test_bemba_cervical_data_identical_to_upstream_runtime_value():
    """Independent audit: the de-duplicated file must load exactly the value the original file
    loaded (its second assignment) in upstream commit 3260259. sha256 of the tuple joined by NUL,
    computed from the upstream file. Any edit to the medical text changes this hash."""
    import hashlib
    from training.cervical_cancer_data_bemba import cervical_cancer_data_bemba as data
    digest = hashlib.sha256("\x00".join(data).encode()).hexdigest()
    assert digest == "e579bdf54de32f912eb6640f10f2e35b5af2922031e06e321eb9d79b9132df6b"
    assert len(data) == 99
