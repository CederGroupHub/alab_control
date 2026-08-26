# Alab Control Components
This python package includes drivers needed to control devices in Ceder group's alab.

## Installation
```shell
pip install .
```

For editable local development, use:

```shell
pip install -e .
```

Note that at least one optional dependency is only available in the Ceder group's private workflow/tooling context. Install it with:

```shell
pip install ".[ceder]"
```

If you need that dependency separately, the requirement is still listed in `requirements_ceder.txt` and can be installed manually with:

```shell
pip install -r requirements_ceder.txt
```



## Test
```shell
python -m unittest
```
