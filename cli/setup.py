from setuptools import setup, find_packages

setup(
    name="alpaca-rl",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.1.0",
        "requests>=2.32.0",
        "rich>=13.0.0",
        "python-dotenv>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "alpaca-rl=alpaca_rl.main:cli",
        ],
    },
    python_requires=">=3.11",
)
