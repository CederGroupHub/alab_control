from setuptools import setup, find_packages

setup(
    name='alab_control',
    packages=find_packages(exclude=["tests", "tests.*"]),
    version='0.1.0',
    author='Alab Project Team',
    python_requires=">3.6",
    description='Drivers for alab devices',
    zip_safe=False,
    install_requires=[
        "pyModbusTCP",
    ],
    include_package_data=True
)
