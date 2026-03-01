---
description: Bootstrap new ML projects with ML4T context and best practices
---

# Project Bootstrap Workflow

This workflow provides a systematic approach to bootstrap new machine learning projects with the ML4T context and best practices we've established.

## Steps

1. **Initialize Project Structure**
   - Create standard directory structure
   - Set up configuration files
   - Initialize version control
   // turbo
2. **Bootstrap ML4T Context**
   - Copy relevant memory entries
   - Import workflow templates
   - Set up project instructions
   - Configure development environment

3. **Create Project-Specific Context**
   - Define project scope and objectives
   - Identify data sources and requirements
   - Set up coding standards and conventions
   - Create project documentation

4. **Set Up Development Infrastructure**
   - Configure development environment
   - Set up testing framework
   - Initialize data pipelines
   - Create monitoring and logging

5. **Validate Bootstrap Process**
   - Test project structure
   - Validate context integration
   - Check development environment
   - Verify documentation completeness

## Bootstrap Commands

### Quick Start
```bash
# Create new project directory
mkdir new_ml_project && cd new_ml_project

# Initialize with ML4T context
windsurf bootstrap --template ml4t

# Set up development environment
windsurf setup-env
```

### Manual Bootstrap
```bash
# Create directory structure
mkdir -p {data,notebooks,src,tests,docs,config,workflows}

# Copy ML4T templates
cp -r ~/.windsurf/workflows/* workflows/
cp -r ~/.windsurf/plans/* plans/

# Initialize memory context
windsurf memory import --template ml4t
```

## Project Templates

### ML4T Trading Project
- **Structure**: Alpha factor research, backtesting, deployment
- **Libraries**: Zipline, Alphalens, pandas, scikit-learn
- **Workflows**: Factor research, model development, backtesting

### General ML Project
- **Structure**: Data processing, modeling, evaluation, deployment
- **Libraries**: scikit-learn, TensorFlow/PyTorch, pandas
- **Workflows**: Data pipeline, model training, evaluation

### Research Project
- **Structure**: Data exploration, experimentation, documentation
- **Libraries**: Jupyter, matplotlib, seaborn, statsmodels
- **Workflows**: Experiment tracking, result analysis, publication

## Context Integration

### Memory System Setup
```python
# Import ML4T context memories
windsurf memory create --template ml4t-project-context
windsurf memory create --template ml4t-coding-standards
windsurf memory create --template ml4t-workflows
```

### Workflow Integration
```python
# Copy relevant workflows
cp ~/.windsurf/workflows/alpha-factor-research.md workflows/
cp ~/.windsurf/workflows/ml-model-development.md workflows/
cp ~/.windsurf/workflows/strategy-backtesting.md workflows/
```

### Project Instructions
```python
# Create project-specific instructions
windsurf plan create --template ml4t-project-instructions
windsurf plan create --template project-structure
```

## Automation Scripts

### Bootstrap Script
```python
#!/usr/bin/env python3
"""
ML4T Project Bootstrap Script

Automates the setup of new ML projects with ML4T context and best practices.
"""

import os
import shutil
import argparse
from pathlib import Path

def create_project_structure(project_name, project_type="ml4t"):
    """Create standard project directory structure"""
    
    base_dirs = {
        "ml4t": ["data", "notebooks", "src", "tests", "docs", "config", "workflows"],
        "general": ["data", "src", "tests", "docs", "config", "scripts"],
        "research": ["data", "notebooks", "results", "docs", "config"]
    }
    
    for dir_name in base_dirs.get(project_type, base_dirs["general"]):
        Path(dir_name).mkdir(parents=True, exist_ok=True)
        
    print(f"Created project structure for {project_type}")

def copy_ml4t_context():
    """Copy ML4T context files to new project"""
    
    # Copy workflows
    workflows_dir = Path.home() / ".windsurf/workflows"
    if workflows_dir.exists():
        shutil.copytree(workflows_dir, "workflows", dirs_exist_ok=True)
        print("Copied ML4T workflows")
    
    # Copy plans
    plans_dir = Path.home() / ".windsurf/plans"
    if plans_dir.exists():
        shutil.copytree(plans_dir, "plans", dirs_exist_ok=True)
        print("Copied ML4T plans")

def create_project_config(project_name, project_type):
    """Create project configuration files"""
    
    config = {
        "project_name": project_name,
        "project_type": project_type,
        "created": datetime.now().isoformat(),
        "ml4t_version": "2.0",
        "python_version": "3.9+"
    }
    
    with open("config/project_config.yaml", "w") as f:
        yaml.dump(config, f, default_flow_style=False)
    
    print(f"Created project config for {project_name}")

def setup_git_repo():
    """Initialize git repository"""
    
    os.system("git init")
    
    # Create .gitignore
    gitignore = """
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

# Jupyter
.ipynb_checkpoints

# Data
data/raw/
data/processed/
*.h5
*.hdf5
*.csv
*.parquet

# Models
models/
*.pkl
*.joblib

# Environment
.env
.venv/
env/
venv/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
"""
    
    with open(".gitignore", "w") as f:
        f.write(gitignore)
    
    print("Initialized git repository")

def main():
    parser = argparse.ArgumentParser(description="Bootstrap ML4T project")
    parser.add_argument("name", help="Project name")
    parser.add_argument("--type", choices=["ml4t", "general", "research"], 
                       default="ml4t", help="Project type")
    parser.add_argument("--no-context", action="store_true", 
                       help="Skip ML4T context copying")
    
    args = parser.parse_args()
    
    print(f"Bootstrapping {args.name} project...")
    
    # Create project structure
    create_project_structure(args.name, args.type)
    
    # Copy ML4T context
    if not args.no_context:
        copy_ml4t_context()
    
    # Create project config
    create_project_config(args.name, args.type)
    
    # Setup git
    setup_git_repo()
    
    print(f"✓ Project {args.name} bootstrapped successfully!")
    print(f"✓ Type: {args.type}")
    print(f"✓ ML4T context: {'Included' if not args.no_context else 'Skipped'}")

if __name__ == "__main__":
    main()
```

## Context Templates

### Memory Templates
```python
# Template for project context memory
PROJECT_CONTEXT_TEMPLATE = """
# {project_name} Project Context

## Project Overview
{project_description}

## Project Structure
{project_structure}

## Key Technologies
{technologies}

## Data Sources
{data_sources}

## ML4T Workflow
{workflow}

## Key Concepts
{concepts}

## Coding Standards
{coding_standards}
"""

# Template for coding standards memory
CODING_STANDARDS_TEMPLATE = """
# {project_name} Coding Standards

## Code Organization
{code_organization}

## Data Management
{data_management}

## Model Development
{model_development}

## Testing Requirements
{testing_requirements}

## Documentation Standards
{documentation_standards}
"""
```

### Workflow Templates
```python
# Template for custom workflows
WORKFLOW_TEMPLATE = """
---
description: {workflow_description}
---

# {workflow_title}

{workflow_steps}

## Key Tools and Libraries

{tools_libraries}

## Best Practices

{best_practices}

## Common Pitfalls to Avoid

{common_pitfalls}
"""
```

## Validation Checklist

### Project Structure Validation
- [ ] All required directories created
- [ ] Configuration files present
- [ ] Git repository initialized
- [ ] .gitignore properly configured

### Context Integration Validation
- [ ] Memory entries imported
- [ ] Workflows copied and customized
- [ ] Project instructions created
- [ ] Documentation complete

### Development Environment Validation
- [ ] Python environment set up
- [ ] Dependencies installed
- [ ] Testing framework configured
- [ ] CI/CD pipeline ready

## Usage Examples

### Bootstrap New ML4T Project
```bash
# Create new ML4T trading project
python bootstrap.py my_trading_project --type ml4t

# Create general ML project without ML4T context
python bootstrap.py my_ml_project --type general --no-context

# Create research project
python bootstrap.py my_research --type research
```

### Manual Context Setup
```bash
# After project creation, manually set up context
windsurf memory create --content-file project_context.md
windsurf workflow import --source ~/.windsurf/workflows/
windsurf plan create --template project_instructions
```

## Best Practices

### Project Initialization
1. **Choose appropriate template** based on project needs
2. **Customize context** for project-specific requirements
3. **Set up version control** from the beginning
4. **Configure development environment** early

### Context Management
1. **Import relevant memories** from established projects
2. **Customize workflows** for specific use cases
3. **Create project-specific instructions** for team alignment
4. **Maintain consistency** across related projects

### Automation
1. **Use bootstrap scripts** for reproducible setup
2. **Template customization** for different project types
3. **Validation checks** to ensure completeness
4. **Documentation updates** as context evolves

## Troubleshooting

### Common Issues
- **Missing context files**: Check Windsurf configuration
- **Permission errors**: Ensure proper file permissions
- **Template conflicts**: Resolve naming conflicts manually
- **Environment issues**: Verify Python and package versions

### Solutions
- **Manual context copy**: If automation fails
- **Template customization**: Adapt for specific needs
- **Incremental setup**: Bootstrap in stages
- **Validation debugging**: Check each step individually

This workflow provides a comprehensive approach to bootstrapping new projects with established ML4T context and best practices, ensuring consistency and quality across all projects.
