# Alab Control Components
This python package includes drivers needed to control devices in Ceder group's alab.

## Installation
```shell
python setup.py install
```

Note that at least one requirement is only available in the Ceder group's private repository. These requirements are contained in the `requirements_ceder.txt` file and can be included by installing with `pip install alab_control[ceder]`. Alternatively, you can install the requirements manually with

```shell
pip install -r requirements_ceder.txt
```



## Test
```shell
python -m unittest
```