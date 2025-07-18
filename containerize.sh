#!/bin/bash

# Set variables
REGION="asia-south1"
PROJECT_ID="observability-project-466314" # project-id
REPO_NAME="observability-images" # repo name
BASE_IMAGE_NAME="observability-demo" # base image name

# List of service folders
SERVICES=("frontend" "cart-service" "order-service" "product-service")

# Loop through each service and build & push Docker image
for SERVICE in "${SERVICES[@]}"; do
    echo "---------------------------------------------"
    echo "Building and pushing image for $SERVICE..."

    # Check if directory exists
    if [ -d "$SERVICE" ]; then
        IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/${BASE_IMAGE_NAME}_$SERVICE:latest"

        # Build the Docker image
        docker build -t "$IMAGE_TAG" "$SERVICE"

        # Push the image to Google Artifact Registry
        docker push "$IMAGE_TAG"

        echo "Successfully pushed $IMAGE_TAG"
    else
        echo "Directory $SERVICE does not exist. Skipping..."
    fi

    echo
done

echo "✅ All done with containerization and push."
