# Traffic Light Control System

A Flask-based web application that provides a configurable traffic light with REST API endpoints.

## Features

- **Visual Traffic Light**: Interactive web interface with animated traffic light
- **RESTful API**: Full API to read and control traffic light status
- **Real-time Updates**: Live updates when traffic light changes
- **API Documentation**: Built-in comprehensive API documentation
- **Modern UI**: Beautiful interface built with Tailwind CSS

## Quick Start

### Option 1: Docker Deployment (Recommended)

1. **Build and Run with Docker**
   ```bash
   # Using the deployment script
   ./deploy.sh start
   
   # Or manually with Docker
   docker build -t traffic-light-app .
   docker run -d -p 5000:5000 --name traffic-light-container traffic-light-app
   ```

2. **Access the Application**
   - Main Interface: http://localhost:5000
   - API Documentation: http://localhost:5000/docs

3. **Management Commands**
   ```bash
   ./deploy.sh status    # Check application status
   ./deploy.sh logs      # View application logs
   ./deploy.sh restart   # Restart the application
   ./deploy.sh stop      # Stop the application
   ./deploy.sh clean     # Clean up containers and images
   ```

### Option 2: Local Python Development

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Application**
   ```bash
   python app.py
   ```

3. **Access the Application**
   - Main Interface: http://localhost:5000
   - API Documentation: http://localhost:5000/docs

## API Endpoints

### Get Current Status
```bash
GET /api/traffic-light/status
```

### Set Traffic Light Color
```bash
POST /api/traffic-light/status
Content-Type: application/json

{
  "color": "red|yellow|green"
}
```

### Get Valid Colors
```bash
GET /api/traffic-light/colors
```

## Example Usage

### Using curl

```bash
# Get current status
curl -X GET http://localhost:5000/api/traffic-light/status

# Set traffic light to green
curl -X POST http://localhost:5000/api/traffic-light/status \
  -H "Content-Type: application/json" \
  -d '{"color": "green"}'

# Get valid colors
curl -X GET http://localhost:5000/api/traffic-light/colors
```

### Using the Web Interface

1. Navigate to http://localhost:5000
2. Click the colored buttons to change the traffic light
3. Watch the traffic light animation update in real-time
4. View the current status below the traffic light

## API Documentation

Visit http://localhost:5000/docs for complete API documentation including:
- Detailed endpoint descriptions
- Request/response examples
- Error handling
- Testing instructions
- 
## DevRev AI Agent Integration with Ngrok

### Making Your TrafficLight Available Over the Internet

To enable DevRev's AI agent to connect to your TrafficLight application and integrate it into Agentic workflows, you need to expose your local application to the internet using Ngrok.

### Prerequisites

1. **Install Ngrok**
   ```bash
   # macOS
   brew install ngrok
   
   # Or download from https://ngrok.com/download
   ```

2. **Sign up for Ngrok** (free tier available)
   - Create account at https://ngrok.com/
   - Get your authtoken from the dashboard

3. **Configure Ngrok**
   ```bash
   ngrok config add-authtoken YOUR_AUTHTOKEN
   ```

### Setup Instructions

1. **Start Your TrafficLight Application**
   ```bash
   # Using Docker (recommended)
   docker run -d -p 8080:5000 --name trafficlight-container trafficlight-app
   
   # Or locally
   python app.py
   ```

2. **Expose Application with Ngrok**
   ```bash
   # If running on port 8080 (Docker)
   ngrok http 8080
   
   # If running locally on port 5000
   ngrok http 5000
   ```

3. **Copy Your Public URL**
   Ngrok will display something like:
   ```
   Forwarding    https://abc123.ngrok.io -> http://localhost:8080
   ```
   Your public TrafficLight URL is: `https://abc123.ngrok.io`

### DevRev Workflow Integration

The TrafficLight application comes with **4 example workflows** for DevRev AI agent integration:

1. **Workflow 1**: Redirects conversations to the Agent. (no URL changes needed) 
2. **Workflow 2**: Traffic light control automation (⚠️ **requires URL update**)
3. **Workflow 3**: Emergency response traffic management (⚠️ **requires URL update**)  
4. **Workflow 4**: Advanced traffic coordination (⚠️ **requires URL update**)

To have a functioning setup, make sure to create an agent first (and link Workflow 1 to it) , and give it a basic prompt instructing it to help customers
with all their trafficlight inquiries.

### Important: Update Workflow URLs

**For workflows 2, 3, and 4**, you must update the hardcoded URLs to point to your specific Ngrok URL:

1. **Find your workflows** in the DevRev platform
2. **Replace the URL** in each workflow configuration:
   - Change: `http://localhost:5000` or `http://localhost:8080`
   - To: `https://your-ngrok-url.ngrok.io`

### API Endpoints (External Access)

Once Ngrok is running, your TrafficLight API will be accessible at:

```bash
# Get current status
curl https://your-ngrok-url.ngrok.io/api/traffic-light/status

# Set traffic light color
curl -X POST https://your-ngrok-url.ngrok.io/api/traffic-light/status \
  -H "Content-Type: application/json" \
  -d '{"color": "green"}'

# Get valid colors  
curl https://your-ngrok-url.ngrok.io/api/traffic-light/colors

# Access web interface
https://your-ngrok-url.ngrok.io
```

### Benefits for DevRev Integration

- **Real-time Control**: AI agents can change traffic light states instantly
- **Status Monitoring**: Agents can check current traffic light status
- **Workflow Automation**: Integrate traffic control into complex business processes
- **Emergency Response**: Enable automated traffic management during incidents
- **Testing & Demo**: Perfect for demonstrating AI-driven infrastructure control

### Security Considerations

- Ngrok free tier creates public URLs accessible to anyone
- Consider Ngrok's paid plans for password protection and custom domains
- Monitor Ngrok dashboard for traffic and usage
- Remember to stop Ngrok tunnel when not needed

## Technology Stack

- **Backend**: Python Flask
- **Frontend**: HTML5, JavaScript, Tailwind CSS
- **API**: RESTful JSON API
- **Storage**: In-memory (resets on restart)
- **Containerization**: Docker with multi-stage builds
- **Deployment**: Docker Compose with health checks

## Configuration

The application runs on `localhost:5000` by default. Valid traffic light colors are:
- `red`
- `yellow`
- `green`

## Docker Deployment

The application is containerized using Docker for easy deployment and consistency across environments.

### Docker Files
- **Dockerfile**: Defines the container image with Python 3.11 slim base
- **docker-compose.yml**: Simplified deployment configuration
- **deploy.sh**: Management script for easy container operations
- **.dockerignore**: Excludes unnecessary files from build context

### Container Features
- **Security**: Runs as non-root user
- **Health Checks**: Built-in health monitoring
- **Port Mapping**: Maps container port 5000 to host port 5000
- **Auto-restart**: Container restarts unless explicitly stopped
- **Logging**: Centralized logging accessible via `docker logs`

## Development

The application uses Flask's development server with debug mode enabled. For production deployment, use a proper WSGI server like Gunicorn.

## License

This project is open source and available under the MIT License. 