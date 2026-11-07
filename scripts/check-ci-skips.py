"""Reject every pytest skip except the documented absent meaning-model files."""
import re
import sys
import xml.etree.ElementTree as ET

report = ET.parse(sys.argv[1])
allowed = 0
for case in report.iter("testcase"):
    for skip in case.findall("skipped"):
        if (case.get("classname") == "tests.test_search_model"
                and re.fullmatch(r"the model embeddinggemma-300m-q4 is not in .+", skip.get("message", ""))):
            allowed += 1
        else:
            # Counts only: a future unexpected skip must not expose a path or test data.
            sys.exit("Unexpected test skip: CI permits only missing meaning-model files")
print(f"CI skip check: {allowed} intended model-file skips, 0 unexpected skips")
