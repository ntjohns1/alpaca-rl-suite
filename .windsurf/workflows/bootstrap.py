#!/usr/bin/env python3
"""
ML4T Project Bootstrap Script

Automates the setup of new ML projects with ML4T context and best practices.
Usage: python bootstrap.py <project_name> [--type ml4t|general|research] [--no-context]
"""

import os
import sys
import shutil
import argparse
import yaml
from datetime import datetime
from pathlib import Path

class ML4TBootstrap:
    """Bootstrap class for ML4T projects"""
    
    def __init__(self, project_name, project_type="ml4t", include_context=True):
        self.project_name = project_name
        self.project_type = project_type
        self.include_context = include_context
        self.windsurf_dir = Path.home() / ".windsurf"
        
    def create_project_structure(self):
        """Create standard project directory structure"""
        
        base_dirs = {
            "ml4t": [
                "data/raw", "data/processed", "data/external",
                "notebooks/research", "notebooks/development", "notebooks/production",
                "src/features", "src/models", "src/evaluation", "src/utils",
                "tests/unit", "tests/integration", "tests/performance",
                "docs/api", "docs/user_guide", "docs/technical",
                "config", "scripts", "workflows", "plans"
            ],
            "general": [
                "data/raw", "data/processed", "data/external",
                "src/data", "src/features", "src/models", "src/evaluation", "src/utils",
                "tests/unit", "tests/integration",
                "docs", "config", "scripts", "workflows", "plans"
            ],
            "research": [
                "data/raw", "data/processed",
                "notebooks/exploration", "notebooks/experiments", "notebooks/results",
                "src/analysis", "src/visualization", "src/utils",
                "results/figures", "results/tables", "results/papers",
                "docs", "config", "workflows", "plans"
            ]
        }
        
        directories = base_dirs.get(self.project_type, base_dirs["general"])
        
        for dir_path in directories:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
            
        print(f"✓ Created project structure for {self.project_type}")
        
    def copy_ml4t_context(self):
        """Copy ML4T context files to new project"""
        
        if not self.include_context:
            print("⚠ Skipping ML4T context copy")
            return
            
        # Copy workflows
        workflows_source = self.windsurf_dir / "workflows"
        workflows_target = Path("workflows")
        
        if workflows_source.exists():
            workflows_target.mkdir(exist_ok=True)
            for workflow_file in workflows_source.glob("*.md"):
                shutil.copy2(workflow_file, workflows_target / workflow_file.name)
            print("✓ Copied ML4T workflows")
        
        # Copy plans
        plans_source = self.windsurf_dir / "plans"
        plans_target = Path("plans")
        
        if plans_source.exists():
            plans_target.mkdir(exist_ok=True)
            for plan_file in plans_source.glob("*.md"):
                shutil.copy2(plan_file, plans_target / plan_file.name)
            print("✓ Copied ML4T plans")
            
    def create_project_config(self):
        """Create project configuration files"""
        
        config = {
            "project_name": self.project_name,
            "project_type": self.project_type,
            "created": datetime.now().isoformat(),
            "ml4t_version": "2.0",
            "python_version": "3.9+",
            "author": os.getenv("USER", "Unknown"),
            "description": f"{self.project_name} - {self.project_type} project"
        }
        
        # Create config directory
        Path("config").mkdir(exist_ok=True)
        
        # Save project config
        with open("config/project_config.yaml", "w") as f:
            yaml.dump(config, f, default_flow_style=False)
        
        print(f"✓ Created project config for {self.project_name}")
        
    def create_requirements(self):
        """Create requirements.txt based on project type"""
        
        requirements = {
            "ml4t": [
                "pandas>=1.3.0",
                "numpy>=1.21.0",
                "scikit-learn>=1.0.0",
                "matplotlib>=3.4.0",
                "seaborn>=0.11.0",
                "jupyter>=1.0.0",
                "zipline-reloaded>=2.1.0",
                "alphalens>=0.4.0",
                "pyfolio>=0.9.0",
                "TA-Lib>=0.4.0",
                "statsmodels>=0.12.0",
                "scipy>=1.7.0",
                "PyYAML>=5.4.0",
                "tqdm>=4.62.0"
            ],
            "general": [
                "pandas>=1.3.0",
                "numpy>=1.21.0",
                "scikit-learn>=1.0.0",
                "matplotlib>=3.4.0",
                "seaborn>=0.11.0",
                "jupyter>=1.0.0",
                "scipy>=1.7.0",
                "PyYAML>=5.4.0",
                "tqdm>=4.62.0"
            ],
            "research": [
                "pandas>=1.3.0",
                "numpy>=1.21.0",
                "matplotlib>=3.4.0",
                "seaborn>=0.11.0",
                "jupyter>=1.0.0",
                "scipy>=1.7.0",
                "statsmodels>=0.12.0",
                "PyYAML>=5.4.0",
                "tqdm>=4.62.0",
                "plotly>=5.0.0",
                "nbconvert>=6.0.0"
            ]
        }
        
        with open("requirements.txt", "w") as f:
            for package in requirements.get(self.project_type, requirements["general"]):
                f.write(f"{package}\n")
        
        print(f"✓ Created requirements.txt for {self.project_type}")
        
    def setup_git_repo(self):
        """Initialize git repository"""
        
        # Initialize git
        os.system("git init")
        
        # Create .gitignore
        gitignore_content = """
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# Jupyter
.ipynb_checkpoints
*.ipynb

# Data
data/raw/*
data/processed/*
!data/raw/.gitkeep
!data/processed/.gitkeep
*.h5
*.hdf5
*.csv
*.parquet
*.json
*.pkl
*.joblib

# Models
models/*
!models/.gitkeep

# Environment
.env
.venv/
env/
venv/
ENV/
env.bak/
venv.bak/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
.DS_Store?
._*
.Spotlight-V100
.Trashes
ehthumbs.db
Thumbs.db

# Logs
logs/
*.log

# Results
results/*
!results/.gitkeep

# Config (keep structure, ignore secrets)
config/secrets.yaml
config/local.yaml
"""
        
        with open(".gitignore", "w") as f:
            f.write(gitignore_content)
        
        # Create .gitkeep files to preserve empty directories
        gitkeep_dirs = [
            "data/raw", "data/processed", "models", "results",
            "logs", "notebooks", "src", "tests", "docs"
        ]
        
        for dir_path in gitkeep_dirs:
            if Path(dir_path).exists():
                (Path(dir_path) / ".gitkeep").touch()
        
        print("✓ Initialized git repository")
        
    def create_readme(self):
        """Create README.md"""
        
        readme_content = f"""# {self.project_name}

{self.project_name.title()} - {self.project_type} project

## Project Structure

```
{self.project_name}/
├── data/                   # Data files
│   ├── raw/               # Raw data
│   ├── processed/         # Processed data
│   └── external/          # External data sources
├── notebooks/              # Jupyter notebooks
├── src/                   # Source code
├── tests/                 # Test files
├── docs/                  # Documentation
├── config/                # Configuration files
├── scripts/               # Utility scripts
├── workflows/             # ML4T workflows
└── plans/                 # Project plans
```

## Setup

1. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\\Scripts\\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up ML4T context:
```bash
# Import ML4T workflows and plans
windsurf context import
```

## Usage

### Development
```bash
# Start Jupyter notebook
jupyter notebook

# Run tests
python -m pytest tests/

# Format code
black src/ tests/
```

### ML4T Workflows
- `/alpha-factor-research` - Alpha factor research workflow
- `/ml-model-development` - ML model development workflow
- `/strategy-backtesting` - Strategy backtesting workflow

## Documentation

- [Project Documentation](docs/)
- [ML4T Guidelines](docs/ml4t_guidelines.md)
- [API Reference](docs/api/)

## Contributing

1. Follow ML4T coding standards
2. Write comprehensive tests
3. Update documentation
4. Use semantic versioning

## License

MIT License - see LICENSE file for details

## Created

- Date: {datetime.now().strftime('%Y-%m-%d')}
- Type: {self.project_type}
- ML4T Version: 2.0
"""
        
        with open("README.md", "w") as f:
            f.write(readme_content)
        
        print("✓ Created README.md")
        
    def create_setup_py(self):
        """Create setup.py for package installation"""
        
        setup_content = f'''
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="{self.project_name.lower().replace(' ', '_')}",
    version="0.1.0",
    author="{os.getenv('USER', 'Unknown')}",
    description="{self.project_name} - {self.project_type} project",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(where="src"),
    package_dir={{"": "src"}},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.9",
    install_requires=requirements,
    extras_require={{
        "dev": [
            "pytest>=6.0",
            "black>=21.0",
            "flake8>=3.9",
            "mypy>=0.910",
        ],
    }},
)
'''
        
        with open("setup.py", "w") as f:
            f.write(setup_content)
        
        print("✓ Created setup.py")
        
    def validate_bootstrap(self):
        """Validate that bootstrap was successful"""
        
        validation_results = {
            "directories": [],
            "files": [],
            "context": False
        }
        
        # Check directories
        required_dirs = ["src", "tests", "docs", "config"]
        for dir_name in required_dirs:
            if Path(dir_name).exists():
                validation_results["directories"].append(dir_name)
        
        # Check files
        required_files = ["README.md", "requirements.txt", ".gitignore"]
        for file_name in required_files:
            if Path(file_name).exists():
                validation_results["files"].append(file_name)
        
        # Check ML4T context
        if self.include_context:
            if Path("workflows").exists() and len(list(Path("workflows").glob("*.md"))) > 0:
                validation_results["context"] = True
        
        # Print validation results
        print("\n=== Bootstrap Validation ===")
        print(f"Directories created: {len(validation_results['directories'])}/{len(required_dirs)}")
        print(f"Files created: {len(validation_results['files'])}/{len(required_files)}")
        print(f"ML4T context: {'✓' if validation_results['context'] else '✗'}")
        
        if validation_results["context"] or not self.include_context:
            print("\n✓ Bootstrap completed successfully!")
        else:
            print("\n⚠ Bootstrap completed with warnings")
        
        return validation_results
        
    def run_bootstrap(self):
        """Run complete bootstrap process"""
        
        print(f"🚀 Bootstrapping {self.project_name} project...")
        print(f"📁 Type: {self.project_type}")
        print(f"🧠 ML4T Context: {'Included' if self.include_context else 'Skipped'}")
        print()
        
        try:
            # Create project structure
            self.create_project_structure()
            
            # Copy ML4T context
            self.copy_ml4t_context()
            
            # Create configuration files
            self.create_project_config()
            self.create_requirements()
            
            # Setup version control
            self.setup_git_repo()
            
            # Create documentation
            self.create_readme()
            self.create_setup_py()
            
            # Validate bootstrap
            self.validate_bootstrap()
            
            print(f"\n🎉 Project {self.project_name} bootstrapped successfully!")
            print(f"\nNext steps:")
            print(f"1. cd {self.project_name}")
            print(f"2. python -m venv venv")
            print(f"3. source venv/bin/activate  # On Windows: venv\\Scripts\\activate")
            print(f"4. pip install -r requirements.txt")
            if self.include_context:
                print(f"5. windsurf context import  # Import ML4T context")
            print(f"6. jupyter notebook  # Start development")
            
        except Exception as e:
            print(f"\n❌ Bootstrap failed: {e}")
            sys.exit(1)


def main():
    """Main entry point"""
    
    parser = argparse.ArgumentParser(
        description="Bootstrap ML4T project with context and best practices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bootstrap.py my_trading_project --type ml4t
  python bootstrap.py my_ml_project --type general --no-context
  python bootstrap.py my_research --type research
        """
    )
    
    parser.add_argument("name", help="Project name")
    parser.add_argument(
        "--type", 
        choices=["ml4t", "general", "research"], 
        default="ml4t", 
        help="Project type (default: ml4t)"
    )
    parser.add_argument(
        "--no-context", 
        action="store_true", 
        help="Skip ML4T context copying"
    )
    
    args = parser.parse_args()
    
    # Validate project name
    if not args.name or not args.name.replace("_", "").replace("-", "").isalnum():
        print("❌ Invalid project name. Use alphanumeric characters, hyphens, and underscores only.")
        sys.exit(1)
    
    # Create project directory
    project_dir = Path(args.name)
    if project_dir.exists():
        print(f"❌ Directory '{args.name}' already exists.")
        sys.exit(1)
    
    project_dir.mkdir()
    os.chdir(project_dir)
    
    # Run bootstrap
    bootstrap = ML4TBootstrap(
        project_name=args.name,
        project_type=args.type,
        include_context=not args.no_context
    )
    
    bootstrap.run_bootstrap()


if __name__ == "__main__":
    main()
