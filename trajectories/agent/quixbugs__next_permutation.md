# Trajectory — `quixbugs__next_permutation` (agent)

## 1. `reproduce`

**Tool call**

```
pytest python_testcases/test_next_permutation.py
```

**Tool response**

```text
8 failing test(s):
  python_testcases/test_next_permutation.py::test_next_permutation[input_data0-expected0]
  python_testcases/test_next_permutation.py::test_next_permutation[input_data1-expected1]
  python_testcases/test_next_permutation.py::test_next_permutation[input_data2-expected2]
  python_testcases/test_next_permutation.py::test_next_permutation[input_data3-expected3]
  python_testcases/test_next_permutation.py::test_next_permutation[input_data4-expected4]
  python_testcases/test_next_permutation.py::test_next_permutation[input_data5-expected5]
  python_testcases/test_next_permutation.py::test_next_permutation[input_data6-expected6]
  python_testcases/test_next_permutation.py::test_next_permutation[input_data7-expected7]

--- python_testcases/test_next_permutation.py::test_next_permutation[input_data0-expected0] ---
E   assert [3, 1, 2, 4] == [3, 4, 1, 2]
      
      At index 1 diff: 1 != 4
      Use -v to get more diff

--- python_testcases/test_next_permutation.py::test_next_permutation[input_data1-expected1] ---
E   assert [3, 1, 5, 2, 6] == [3, 6, 1, 2, 5]
      
      At index 1 diff: 1 != 6
      Use -v to get more diff

--- python_testcases/test_next_permutation.py::test_next_permutation[input_data2-expected2] ---
E   assert [3, 2, 5, 6] == [3, 6, 2, 5]
      
      At index 1 diff: 2 != 6
      Use -v to get more diff
```

**Gate decision** — bug reproduced


## 2. `localize`

**Tool response**

```text
target file: python_programs/next_permutation.py
function: next_permutation
traceback frames seen: 0
```

**Gate decision** — localized


## 3. `patch`

**Instruction to the worker**

```text
The function `next_permutation` in `python_programs/next_permutation.py` is failing its test suite.

Documented behaviour:
  (see the function docstring)

Failing tests:
  - python_testcases/test_next_permutation.py::test_next_permutation[input_data0-expected0]
  - python_testcases/test_next_permutation.py::test_next_permutation[input_data1-expected1]
  - python_testcases/test_next_permutation.py::test_next_permutation[input_data2-expected2]
  - python_testcases/test_next_permutation.py::test_next_permutation[input_data3-expected3]
  - python_testcases/test_next_permutation.py::test_next_permutation[input_data4-expected4]
  - python_testcases/test_next_permutation.py::test_next_permutation[input_data5-expected5]
  ... and 2 more

Fix the bug in `python_programs/next_permutation.py` so the failing tests pass.
Do not modify anything under `python_testcases/` or `json_testcases/`, and do not modify `conftest.py` -- only the implementation may change.
If the tests appear to contradict the documented behaviour, say so instead of changing code to match them.

Current contents of `python_programs/next_permutation.py`:

```python

def next_permutation(perm):
    for i in range(len(perm) - 2, -1, -1):
        if perm[i] < perm[i + 1]:
            for j in range(len(perm) - 1, i, -1):
                if perm[j] < perm[i]:
                    next_perm = list(perm)
                    next_perm[i], next_perm[j] = perm[j], perm[i]
                    next_perm[i + 1:] = reversed(next_perm[i + 1:])
                    return next_perm



"""
Next Permutation
next-perm


Input:
    perm: A list of unique ints

Precondition:
    perm is not sorted in reverse order

Output:
    The lexicographically next permutation of the elements of perm

Example:
    >>> next_permutation([3, 2, 4, 1])
    [3, 4, 1, 2]
"""
```
```

**Tool call**

```
write python_programs/next_permutation.py (29 lines)
```

**Tool response**

```text
```python
def next_permutation(perm):
    """
    Return the lexicographically next permutation of the list `perm`.

    The algorithm follows the standard next‑permutation procedure:
    1. Find the largest index `i` such that `perm[i] < perm[i+1]`.
    2. Find the largest index `j` greater than `i` such that `perm[j] > perm[i]`.
    3. Swap `perm[i]` and `perm[j]`.
    4. Reverse the sub‑list `perm[i+1:]`.

    It is assumed that `perm` is not sorted in reverse order, so a next
    permutation always exists.
    """
    # Step 1: find pivot
    for i in range(len(perm) - 2, -1, -1):
        if perm[i] < perm[i + 1]:
            # Step 2: find rightmost successor to pivot
            for j in range(len(perm) - 1, i, -1):
                if perm[j] > perm[i]:
                    # Step 3: swap pivot with successor
                    next_perm = list(perm)
                    next_perm[i], next_perm[j] = next_perm[j], next_perm[i]
                    # Step 4: reverse the suffix
                    next_perm[i + 1:] = list(reversed(next_perm[i + 1:]))
                    return next_perm
    # If no pivot is found, the input is the highest permutation.
    # According to the precondition this should not happen, but we
    # return the input unchanged to be safe.
    return list(perm)
```
```

**Gate decision** — patch applied to workspace


## 4. `verify`

**Tool call**

```
pytest python_testcases/test_next_permutation.py
```

**Tool response**

```text
0 failing test(s):
```

**Gate decision** — PASS — target tests green


## 5. `anticheat`

**Tool call**

```
diff against pristine; protected=['python_testcases', 'json_testcases', 'conftest.py']
```

**Tool response**

```text
no protected file modified
```

**Gate decision** — PASS — tests untouched


## 6. `regression`

**Tool call**

```
pytest python_testcases (60 PASS_TO_PASS nodes)
```

**Tool response**

```text
no regressions
```

**Gate decision** — PASS — nothing regressed


## 7. `checkpoint`

**Tool response**

```text
--- a/python_programs/next_permutation.py
+++ b/python_programs/next_permutation.py
@@ -1,31 +1,29 @@
+def next_permutation(perm):
+    """
+    Return the lexicographically next permutation of the list `perm`.
 
-def next_permutation(perm):
+    The algorithm follows the standard next‑permutation procedure:
+    1. Find the largest index `i` such that `perm[i] < perm[i+1]`.
+    2. Find the largest index `j` greater than `i` such that `perm[j] > perm[i]`.
+    3. Swap `perm[i]` and `perm[j]`.
+    4. Reverse the sub‑list `perm[i+1:]`.
+
+    It is assumed that `perm` is not sorted in reverse order, so a next
+    permutation always exists.
+    """
+    # Step 1: find pivot
     for i in range(len(perm) - 2, -1, -1):
         if perm[i] < perm[i + 1]:
+            # Step 2: find rightmost successor to pivot
             for j in range(len(perm) - 1, i, -1):
-                if perm[j] < perm[i]:
+                if perm[j] > perm[i]:
+                    # Step 3: swap pivot with successor
                     next_perm = list(perm)
-                    next_perm[i], next_perm[j] = perm[j], perm[i]
-                    next_perm[i + 1:] = reversed(next_perm[i + 1:])
+                    next_perm[i], next_perm[j] = next_perm[j], next_perm[i]
+                    # Step 4: reverse the suffix
+                    next_perm[i + 1:] = list(reversed(next_perm[i + 1:]))
                     return next_perm
-
-
-
-"""
-Next Permutation
-next-perm
-
-
-Input:
-    perm: A list of unique ints
-
-Precondition:
-    perm is not sorted in reverse order
-
-Output:
-    The lexicograph
... [326 more chars]
```

**Gate decision** — auto-approved (--yes; batch eval)

