#!/bin/bash

# Define the target branch
BRANCH="main"

echo "🔄 Starting Git sync process for the '$BRANCH' branch..."

# Step 1: Pull the latest changes from the main branch
echo "📥 Pulling latest changes from origin/$BRANCH..."
git pull origin "$BRANCH"

# Check if the pull was successful before proceeding
if [ $? -ne 0 ]; then
    echo "❌ Error: git pull failed. You might have merge conflicts to resolve."
    exit 1
fi

# Step 2: Stage all current changes
echo "📦 Staging all current changes..."
git add .

# Step 3: Prompt the user for a commit message
read -p "📝 Enter your commit message: " COMMIT_MSG

# Ensure the commit message is not empty
if [ -z "$COMMIT_MSG" ]; then
    echo "❌ Error: Commit message cannot be empty. Aborting process."
    exit 1
fi

# Step 4: Commit the changes
echo "💾 Committing changes..."
git commit -m "$COMMIT_MSG"

# Step 5: Push to the main branch
echo "🚀 Pushing changes to origin/$BRANCH..."
git push origin "$BRANCH"

echo "✅ All done! Your code has been successfully pushed."
