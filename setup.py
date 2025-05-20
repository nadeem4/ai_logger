from setuptools import setup, find_packages
import os

# Function to read the requirements.txt file
def parse_requirements(filename):
    """Load requirements from a pip requirements file."""
    with open(filename, 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

# Function to read the README.md file for long description
def read_readme(filename="README.md"):
    """Read the README file for use as long_description."""
    curr_dir = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(curr_dir, filename), encoding='utf-8') as f:
        return f.read()

# Get version from ai_logging/__init__.py
# This avoids importing the package directly, which might cause issues if dependencies are not yet installed.
def get_version(rel_path):
    curr_dir = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(curr_dir, rel_path), 'r') as fp:
        for line in fp.read().splitlines():
            if line.startswith('__version__'):
                delim = '"' if '"' in line else "'"
                return line.split(delim)[1]
    raise RuntimeError("Unable to find version string.")

VERSION = get_version("ai_logging/__init__.py") # Path relative to setup.py

# Define core requirements
# Specific versions can be added if necessary, e.g., "pydantic>=2.0"
# For now, let's assume requirements.txt handles versions.
# If requirements.txt is simple, you can list them directly here.
# For more complex scenarios with optional dependencies, use extras_require.
try:
    INSTALL_REQUIRES = parse_requirements("requirements.txt")
except FileNotFoundError:
    # Fallback if requirements.txt is missing, list essential ones
    # This is a basic set; a real project would ensure requirements.txt is accurate.
    print("Warning: requirements.txt not found. Using a minimal set of core dependencies for setup.py.")
    INSTALL_REQUIRES = [
        "pydantic>=2.0.0,<3.0.0",
        "pydantic-settings>=2.0.0,<3.0.0",
        "jinja2>=3.0.0,<4.0.0",
        # Langchain and OpenAI are optional in the sense that the lib can run with placeholders
        # but for full functionality, they are needed.
        # "langchain>=0.1.0,<0.2.0", # Or langchain-core, langchain-openai, etc.
        # "openai>=1.0.0,<2.0.0",
        # "prometheus-client>=0.19.0,<0.20.0" # If metrics are a core feature
    ]
    # It's better to ensure requirements.txt is always present and correct.

setup(
    name="ai_logging",
    version=VERSION,
    author="Nadeem Khan", # Replace with actual author name
    author_email="contact@example.com", # Replace with actual author email
    description="Python logging toolkit with AI-powered analysis and intelligent routing.",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/ai_logging", # Replace with your project's URL
    packages=find_packages(exclude=["tests*", "examples*"]), # Finds ai_logging and its submodules
    include_package_data=True,  # To include non-code files like templates
    install_requires=INSTALL_REQUIRES,
    python_requires=">=3.8", # Specify your minimum Python version
    classifiers=[
        "Development Status :: 3 - Alpha", # Or "4 - Beta", "5 - Production/Stable"
        "Intended Audience :: Developers",
        "Topic :: System :: Logging",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "License :: OSI Approved :: MIT License", # Choose your license
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],
    keywords="logging ai llm gpt langchain monitoring pii prometheus",
    entry_points={
        "console_scripts": [
            "ai-logging-health-check=ai_logging.cli.health_check:main",
        ],
    },
    # Optional: Define extras for optional dependencies
    # extras_require={
    #     "openai": ["openai>=1.0.0,<2.0.0", "langchain-openai>=0.0.5"],
    #     "huggingface": ["transformers>=4.0.0", "torch>=1.8.0", "langchain-community"], # Example
    #     "prometheus": ["prometheus-client>=0.19.0,<0.20.0"],
    #     "all": [ # To install all optional dependencies
    #         "openai>=1.0.0,<2.0.0", "langchain-openai>=0.0.5",
    #         "transformers>=4.0.0", "torch>=1.8.0", "langchain-community",
    #         "prometheus-client>=0.19.0,<0.20.0"
    #     ]
    # },
    project_urls={ # Optional
        "Bug Reports": "https://github.com/yourusername/ai_logging/issues",
        "Source": "https://github.com/yourusername/ai_logging/",
    },
)
