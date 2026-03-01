#!/usr/bin/env python3
"""
ML4T Context Export Script

Exports ML4T context (memories, workflows, plans) for use in new projects.
This creates a portable context package that can be imported into any new project.
"""

import os
import json
import shutil
import argparse
from datetime import datetime
from pathlib import Path

class ML4TContextExporter:
    """Export ML4T context for project bootstrapping"""
    
    def __init__(self, output_dir="ml4t-context-package"):
        self.output_dir = Path(output_dir)
        self.windsurf_dir = Path.home() / ".windsurf"
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
    def create_context_package(self):
        """Create complete context package"""
        
        print(f"📦 Creating ML4T context package...")
        
        # Create output directory
        self.output_dir.mkdir(exist_ok=True)
        
        # Export memories
        self.export_memories()
        
        # Export workflows
        self.export_workflows()
        
        # Export plans
        self.export_plans()
        
        # Create package manifest
        self.create_manifest()
        
        # Create import script
        self.create_import_script()
        
        print(f"✅ Context package created: {self.output_dir}")
        
    def export_memories(self):
        """Export memory entries"""
        
        memories_dir = self.output_dir / "memories"
        memories_dir.mkdir(exist_ok=True)
        
        # Note: In a real implementation, this would interface with Windsurf's memory system
        # For now, we'll create template memory files
        
        memory_templates = {
            "ml4t-project-context.md": """# ML4T Project Context

## Project Overview
This is a comprehensive machine learning for algorithmic trading project based on Stefan Jansen's "Machine Learning for Algorithmic Trading, 2nd Edition."

## Project Structure
- **01_machine_learning_for_trading**: Introduction to ML4T workflow
- **02_market_and_fundamental_data**: Data sourcing and management
- **03_alternative_data**: Alternative data sources
- **04_alpha_factor_research**: Feature engineering and alpha factors
- **05_strategy_evaluation**: Backtesting and performance evaluation
- **06_machine_learning_process**: ML workflow and validation
- **07_linear_models**: Linear regression and statistical models
- **08_ml4t_workflow**: Complete ML4T workflow with Zipline

## Key Technologies
- **Python**: Primary language
- **Jupyter Notebooks**: Main development environment
- **pandas/NumPy**: Data manipulation
- **scikit-learn**: Traditional ML models
- **TensorFlow/PyTorch**: Deep learning
- **Zipline**: Backtesting engine
- **Alphalens**: Factor performance analysis

## ML4T Workflow
1. Data sourcing and management
2. Feature engineering/alpha factor research
3. Model training and validation
4. Strategy backtesting
5. Performance evaluation
6. Portfolio optimization

## Key Concepts
- Alpha factors and signal generation
- Information coefficient (IC) and information ratio (IR)
- Point-in-time data to avoid look-ahead bias
- Cross-validation for time series data
- Factor turnover and trading costs

## Coding Standards
- Jupyter notebooks for exploratory work
- Clear documentation of data sources
- Point-in-time data handling
- Comprehensive backtesting
- Factor performance analysis
""",
            
            "ml4t-coding-standards.md": """# ML4T Coding Standards

## Code Organization
- Use Jupyter notebooks for exploratory analysis
- Organize code by chapter following book structure
- Maintain clear separation between data, features, models, strategies
- Use relative imports and modular design

## Data Management
- Always use point-in-time data to avoid look-ahead bias
- Document data sources, cleaning procedures, assumptions
- Implement data validation checks
- Store processed data separately from raw data

## Feature Engineering
- Apply financial domain knowledge in feature design
- Use information theory to assess signal content
- Implement proper normalization and standardization
- Consider factor turnover and trading costs

## Model Development
- Start with simple baseline models
- Use time series cross-validation
- Implement proper hyperparameter optimization
- Consider model interpretability

## Backtesting Standards
- Use Zipline for backtesting
- Include transaction costs and slippage
- Implement proper risk management
- Conduct out-of-sample testing

## Performance Evaluation
- Report risk-adjusted metrics
- Analyze performance across market regimes
- Evaluate drawdown characteristics
- Compare against benchmarks
""",
            
            "windsurf-advanced-features.md": """# Windsurf Advanced Features

## Memory System
- Global Rules: System-wide coding standards
- User Memories: Project-specific context
- System Memories: Auto-retrieved from conversations

## Workflow System
- Custom workflows in .windsurf/workflows/
- YAML frontmatter + markdown format
- Slash commands for quick execution
- Turbo annotations for auto-running commands

## Project Context Files
- Memory entries: Persistent project knowledge
- Workflow files: Reusable procedures
- Plan files: Architecture docs and requirements

## Key Benefits
1. Persistent Context: Intelligent context retrieval
2. Active Workflows: Execute complex procedures
3. Worktree Isolation: Separate development environments
4. Intelligent Retrieval: System auto-retrieves relevant memories
"""
        }
        
        for filename, content in memory_templates.items():
            with open(memories_dir / filename, "w") as f:
                f.write(content)
        
        print(f"✓ Exported {len(memory_templates)} memory templates")
        
    def export_workflows(self):
        """Export workflow files"""
        
        workflows_dir = self.output_dir / "workflows"
        workflows_dir.mkdir(exist_ok=True)
        
        # Copy existing workflows from .windsurf/workflows
        source_workflows = self.windsurf_dir / "workflows"
        if source_workflows.exists():
            for workflow_file in source_workflows.glob("*.md"):
                shutil.copy2(workflow_file, workflows_dir / workflow_file.name)
        
        print(f"✓ Exported workflows to {workflows_dir}")
        
    def export_plans(self):
        """Export plan files"""
        
        plans_dir = self.output_dir / "plans"
        plans_dir.mkdir(exist_ok=True)
        
        # Copy existing plans from .windsurf/plans
        source_plans = self.windsurf_dir / "plans"
        if source_plans.exists():
            for plan_file in source_plans.glob("*.md"):
                shutil.copy2(plan_file, plans_dir / plan_file.name)
        
        print(f"✓ Exported plans to {plans_dir}")
        
    def create_manifest(self):
        """Create package manifest"""
        
        manifest = {
            "package_name": "ml4t-context-package",
            "version": "2.0.0",
            "created": datetime.now().isoformat(),
            "description": "ML4T context package for project bootstrapping",
            "contents": {
                "memories": "ML4T memory templates and context",
                "workflows": "Reusable ML4T workflows",
                "plans": "Project planning templates"
            },
            "compatibility": {
                "windsurf_version": ">=1.0.0",
                "python_version": ">=3.9"
            },
            "usage": [
                "Extract package to project directory",
                "Run import script to integrate context",
                "Customize for project-specific needs"
            ]
        }
        
        with open(self.output_dir / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
        
        print("✓ Created package manifest")
        
    def create_import_script(self):
        """Create context import script"""
        
        import_script = '''#!/usr/bin/env python3
"""
ML4T Context Import Script

Imports ML4T context from package into current project.
"""

import os
import shutil
import json
from pathlib import Path

class ML4TContextImporter:
    """Import ML4T context into project"""
    
    def __init__(self, package_dir="ml4t-context-package"):
        self.package_dir = Path(package_dir)
        self.project_dir = Path(".")
        
    def import_context(self):
        """Import all context components"""
        
        print("📥 Importing ML4T context...")
        
        # Import memories
        self.import_memories()
        
        # Import workflows
        self.import_workflows()
        
        # Import plans
        self.import_plans()
        
        print("✅ ML4T context imported successfully!")
        
    def import_memories(self):
        """Import memory templates"""
        
        memories_source = self.package_dir / "memories"
        memories_target = Path.home() / ".windsurf" / "memories"
        
        if memories_source.exists():
            memories_target.mkdir(parents=True, exist_ok=True)
            for memory_file in memories_source.glob("*.md"):
                shutil.copy2(memory_file, memories_target / memory_file.name)
            print("✓ Imported memory templates")
        
    def import_workflows(self):
        """Import workflow files"""
        
        workflows_source = self.package_dir / "workflows"
        workflows_target = self.project_dir / "workflows"
        
        if workflows_source.exists():
            workflows_target.mkdir(exist_ok=True)
            for workflow_file in workflows_source.glob("*.md"):
                shutil.copy2(workflow_file, workflows_target / workflow_file.name)
            print("✓ Imported workflows")
        
    def import_plans(self):
        """Import plan files"""
        
        plans_source = self.package_dir / "plans"
        plans_target = self.project_dir / "plans"
        
        if plans_source.exists():
            plans_target.mkdir(exist_ok=True)
            for plan_file in plans_source.glob("*.md"):
                shutil.copy2(plan_file, plans_target / plan_file.name)
            print("✓ Imported plans")

def main():
    """Main entry point"""
    
    importer = ML4TContextImporter()
    importer.import_context()
    
    print("\\nNext steps:")
    print("1. Review imported workflows in ./workflows/")
    print("2. Customize project plans in ./plans/")
    print("3. Start development with ML4T best practices")

if __name__ == "__main__":
    main()
'''
        
        with open(self.output_dir / "import_context.py", "w") as f:
            f.write(import_script)
        
        # Make script executable
        os.chmod(self.output_dir / "import_context.py", 0o755)
        
        print("✓ Created import script")
        
    def create_package_archive(self):
        """Create compressed archive of context package"""
        
        import zipfile
        
        archive_name = f"ml4t-context-package-{self.timestamp}.zip"
        archive_path = self.output_dir.parent / archive_name
        
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in self.output_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(self.output_dir.parent)
                    zipf.write(file_path, arcname)
        
        print(f"✓ Created archive: {archive_path}")
        return archive_path


def main():
    """Main entry point"""
    
    parser = argparse.ArgumentParser(
        description="Export ML4T context for project bootstrapping"
    )
    
    parser.add_argument(
        "--output", 
        default="ml4t-context-package",
        help="Output directory for context package"
    )
    
    parser.add_argument(
        "--archive", 
        action="store_true",
        help="Create compressed archive"
    )
    
    args = parser.parse_args()
    
    # Create context package
    exporter = ML4TContextExporter(args.output)
    exporter.create_context_package()
    
    # Create archive if requested
    if args.archive:
        archive_path = exporter.create_package_archive()
        print(f"\n📦 Context package archived: {archive_path}")
    
    print(f"\n🎯 Usage:")
    print(f"1. Copy package to new project directory")
    print(f"2. Run: python import_context.py")
    print(f"3. Customize for project needs")


if __name__ == "__main__":
    main()
