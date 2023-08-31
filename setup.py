from pathlib import Path
from setuptools import setup, find_packages
from typing import List

THIS_DIR = Path(__file__).parent

with open(THIS_DIR / "README.md", encoding="utf-8") as f:
    long_description = f.read()


def read_requirements(filepath: Path) -> List[str]:
    with open(filepath, encoding="utf-8") as fd:
        return [
            package.strip("\n")
            for package in fd.readlines()
            if not package.startswith("#")
        ]

requirements = read_requirements(THIS_DIR / "requirements.txt")
requirements_ceder = read_requirements(THIS_DIR / "requirements_ceder.txt") #these are internal Ceder group packages that can only be installed with access to private git repos. 

setup(
    name='alab_control',
    packages=find_packages(exclude=["tests", "tests.*"]),
    version='0.1.0',
    author='Alab Project Team',
    python_requires=">3.6",
    description='Drivers for alab devices',
    zip_safe=False,
    install_requires=requirements,
    extras_require={"ceder": requirements_ceder},
    include_package_data=True
)
