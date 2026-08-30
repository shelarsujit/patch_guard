# Trajectory — `quixbugs__next_permutation` (agent-120b)

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
write python_programs/next_permutation.py (34 lines)
```

**Tool response**

```text
```python
def next_permutation(perm):
    """
    Compute the lexicographically next permutation of a list of unique integers.

    Parameters
    ----------
    perm : list[int]
        A list of unique integers that is not sorted in reverse order.

    Returns
    -------
    list[int]
        The next permutation in lexicographic order.

    Example
    -------
    >>> next_permutation([3, 2, 4, 1])
    [3, 4, 1, 2]
    """
    # Find the first index 'i' from the right where perm[i] < perm[i+1]
    for i in range(len(perm) - 2, -1, -1):
        if perm[i] < perm[i + 1]:
            # Find the smallest element greater than perm[i] to the right of i
            for j in range(len(perm) - 1, i, -1):
                if perm[j] > perm[i]:
                    # Create a copy to avoid mutating the input
                    next_perm = list(perm)
                    # Swap the pivot with the chosen element
                    next_perm[i], next_perm[j] = next_perm[j], next_perm[i]
                    # Reverse the suffix to get the smallest lexicographic order
                    next_perm[i + 1:] = reversed(next_perm[i + 1:])
                    return next_perm
    # According to the precondition, this point should never be reached.
    raise ValueError("Input permutation is sorted in reverse order; no next permutation exists.")
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
@@ -1,31 +1,34 @@
+def next_permutation(perm):
+    """
+    Compute the lexicographically next permutation of a list of unique integers.
 
-def next_permutation(perm):
+    Parameters
+    ----------
+    perm : list[int]
+        A list of unique integers that is not sorted in reverse order.
+
+    Returns
+    -------
+    list[int]
+        The next permutation in lexicographic order.
+
+    Example
+    -------
+    >>> next_permutation([3, 2, 4, 1])
+    [3, 4, 1, 2]
+    """
+    # Find the first index 'i' from the right where perm[i] < perm[i+1]
     for i in range(len(perm) - 2, -1, -1):
         if perm[i] < perm[i + 1]:
+            # Find the smallest element greater than perm[i] to the right of i
             for j in range(len(perm) - 1, i, -1):
-                if perm[j] < perm[i]:
+                if perm[j] > perm[i]:
+                    # Create a copy to avoid mutating the input
                     next_perm = list(perm)
-                    next_perm[i], next_perm[j] = perm[j], perm[i]
+                    # Swap the pivot with the chosen element
+                    next_perm[i], next_perm[j] = next_perm[j], next_perm[i]
+                    # Reverse the suffix to get the smallest lexicographic order
                     next_perm[i + 1:] = reversed(next_perm[i + 1:])
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
-    The l
... [305 more chars]
```

**Gate decision** — auto-approved (--yes; batch eval)

