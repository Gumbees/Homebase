#!/usr/bin/env python3
"""
Migration script to rename .env to stack.env for Homebase project.
This script helps users transition from the old .env naming to the new stack.env naming convention.
"""

import os
import shutil
import sys
from pathlib import Path

def migrate_env_file():
    """Migrate .env file to stack.env if it exists."""
    
    current_dir = Path.cwd()
    env_file = current_dir / '.env'
    stack_env_file = current_dir / 'stack.env'
    
    print("🏠 Homebase Environment Migration Script")
    print("=" * 50)
    
    # Check if .env exists
    if not env_file.exists():
        print("✅ No .env file found - nothing to migrate.")
        
        # Check if stack.env.example exists
        if (current_dir / 'stack.env.example').exists():
            print("💡 Found stack.env.example - you can copy it to stack.env and configure it:")
            print("   cp stack.env.example stack.env")
        
        return True
    
    # Check if stack.env already exists
    if stack_env_file.exists():
        print("⚠️  Both .env and stack.env files exist!")
        print(f"   .env size: {env_file.stat().st_size} bytes")
        print(f"   stack.env size: {stack_env_file.stat().st_size} bytes")
        
        response = input("\nDo you want to overwrite stack.env with .env? (y/N): ").strip().lower()
        if response not in ['y', 'yes']:
            print("❌ Migration cancelled. Please manually resolve the conflict.")
            return False
    
    try:
        # Create a backup of the original .env
        backup_file = current_dir / '.env.backup'
        shutil.copy2(env_file, backup_file)
        print(f"📋 Created backup: {backup_file}")
        
        # Copy .env to stack.env
        shutil.copy2(env_file, stack_env_file)
        print(f"✅ Migrated .env → stack.env")
        
        # Ask if user wants to remove the original .env
        response = input("\nDo you want to remove the original .env file? (y/N): ").strip().lower()
        if response in ['y', 'yes']:
            env_file.unlink()
            print("🗑️  Removed original .env file")
        else:
            print("📁 Kept original .env file (you can remove it manually)")
        
        print("\n🎉 Migration completed successfully!")
        print("\nNext steps:")
        print("1. Review your stack.env file and update any necessary values")
        print("2. Run 'docker-compose up' to start the application")
        print("3. The .env.backup file can be removed once you confirm everything works")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        return False

def main():
    """Main function."""
    
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help']:
        print(__doc__)
        print("\nUsage: python migrate_env.py")
        print("\nThis script will:")
        print("1. Check for existing .env file")
        print("2. Create a backup (.env.backup)")
        print("3. Copy .env to stack.env")
        print("4. Optionally remove the original .env file")
        return
    
    try:
        success = migrate_env_file()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n❌ Migration cancelled by user.")
        sys.exit(1)

if __name__ == '__main__':
    main() 