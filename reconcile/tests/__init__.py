"""Test package.

Split by concern so it is obvious what each file protects:

* ``test_parsing``  - the cleaning rules for dirty cells and refs.
* ``test_compare``  - the disagreement decisions (the part the brief asks for).
* ``test_importer`` - that dirty rows survive and nothing is silently dropped.
* ``test_dataset``  - a golden-set regression check against the real CSVs.
* ``test_api``      - tenant isolation and the filter/sort contract.
"""
