# Package imports

The 58 public exports in `proofmap.__all__` keep their original order and return
the exact objects defined in their original modules. Direct submodule imports
and the existing 21 package module attributes remain available.

`import proofmap` loads its public symbols on first access. Its initial
`__dict__` and `vars(proofmap)` therefore contain fewer eagerly populated
attributes. Use `__all__`, `dir(proofmap)`, or normal attribute access to discover
and retrieve public symbols. `dir()` also includes attributes added dynamically.

After a successful first access, the package retains the original object.
Dependency import errors occur on that access, propagate to the caller, and are
not cached; a later access can retry. Unknown attributes raise `AttributeError`.
Parser behavior, source validation, and authority assessment are unchanged.

Reloading the package clears its retained public aliases. Their next access
again retrieves the current original module object; unrelated dynamic package
attributes remain present. Existing references held by callers are unaffected.
