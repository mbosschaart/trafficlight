#!/bin/bash

# Traffic Light App Docker Deployment Script

set -e

CONTAINER_NAME="traffic-light-container"
IMAGE_NAME="traffic-light-app"
PORT="5005"

# Function to print colored messages
print_info() {
    echo -e "\033[0;34m[INFO]\033[0m $1"
}

print_success() {
    echo -e "\033[0;32m[SUCCESS]\033[0m $1"
}

print_error() {
    echo -e "\033[0;31m[ERROR]\033[0m $1"
}

# Function to check if container is running
is_container_running() {
    docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"
}

# Function to check if container exists (running or stopped)
container_exists() {
    docker ps -a --filter "name=$CONTAINER_NAME" --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"
}

# Function to start the application
start() {
    print_info "Starting Traffic Light application..."
    
    # Stop and remove existing container if it exists
    if container_exists; then
        print_info "Stopping existing container..."
        docker stop "$CONTAINER_NAME" 2>/dev/null || true
        docker rm "$CONTAINER_NAME" 2>/dev/null || true
    fi
    
    # Build the image
    print_info "Building Docker image..."
    docker build -t "$IMAGE_NAME" .
    
    # Run the container
    print_info "Starting container..."
    DOCKER_RUN_ARGS=(-d -p "$PORT:8065" --name "$CONTAINER_NAME")
    if [ -f .env ]; then
        DOCKER_RUN_ARGS+=(--env-file .env)
    fi
    docker run "${DOCKER_RUN_ARGS[@]}" "$IMAGE_NAME"
    
    # Wait for container to be ready
    sleep 3
    
    # Check if container is running
    if is_container_running; then
        print_success "Traffic Light application is running!"
        print_info "Access the application at: http://localhost:$PORT"
        print_info "API Documentation: http://localhost:$PORT/docs"
    else
        print_error "Failed to start the application"
        exit 1
    fi
}

# Function to stop the application
stop() {
    print_info "Stopping Traffic Light application..."
    
    if container_exists; then
        docker stop "$CONTAINER_NAME" 2>/dev/null || true
        docker rm "$CONTAINER_NAME" 2>/dev/null || true
        print_success "Application stopped successfully"
    else
        print_info "No container found to stop"
    fi
}

# Function to restart the application
restart() {
    stop
    start
}

# Function to show application status
status() {
    if is_container_running; then
        print_success "Traffic Light application is running"
        docker ps --filter "name=$CONTAINER_NAME"
        echo
        print_info "Testing API endpoint..."
        curl -s http://localhost:$PORT/api/traffic-light/status | python3 -m json.tool || echo "API test failed"
    else
        print_error "Traffic Light application is not running"
    fi
}

# Function to show logs
logs() {
    if container_exists; then
        print_info "Showing logs for Traffic Light application..."
        docker logs "$CONTAINER_NAME" --tail 20 -f
    else
        print_error "No container found to show logs"
    fi
}

# Function to clean up
clean() {
    stop
    print_info "Cleaning up Docker image..."
    docker rmi "$IMAGE_NAME" 2>/dev/null || true
    print_success "Cleanup completed"
}

# Main script logic
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    clean)
        clean
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|clean}"
        echo
        echo "Commands:"
        echo "  start   - Build and start the application"
        echo "  stop    - Stop the application"
        echo "  restart - Restart the application"
        echo "  status  - Show application status"
        echo "  logs    - Show application logs"
        echo "  clean   - Stop and remove all containers and images"
        exit 1
        ;;
esac 