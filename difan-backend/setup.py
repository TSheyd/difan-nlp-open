# not used, maybe can be removed - we install required packages with requirements.txt
from setuptools import find_packages, setup

setup(
    name="difan_backend",
    packages=find_packages(exclude=["difan_backend_tests"]),
    install_requires=[
        "dagster"
    ],
    extras_require={"dev": ["dagster-webserver", "pytest"]},
)
