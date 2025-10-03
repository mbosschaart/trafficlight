from flask import Flask, render_template, jsonify, request
from datetime import datetime
import json

app = Flask(__name__)

# In-memory storage for traffic light state
traffic_light_state = {
    "color": "red",
    "timestamp": datetime.now().isoformat()
}

# Valid traffic light colors
VALID_COLORS = ["red", "yellow", "green"]

@app.route('/')
def index():
    """Main page displaying the traffic light"""
    return render_template('index.html', current_color=traffic_light_state["color"])

@app.route('/docs')
def docs():
    """API documentation page"""
    return render_template('docs.html')

@app.route('/api/traffic-light/status', methods=['GET'])
def get_traffic_light_status():
    """Get the current traffic light status"""
    return jsonify({
        "color": traffic_light_state["color"],
        "timestamp": traffic_light_state["timestamp"],
        "success": True
    })

@app.route('/api/traffic-light/status', methods=['POST'])
def set_traffic_light_status():
    """Set the traffic light color"""
    try:
        data = request.get_json()
        
        if not data or 'color' not in data:
            return jsonify({
                "success": False,
                "error": "Missing 'color' field in request body"
            }), 400
        
        color = data['color'].lower()
        
        if color not in VALID_COLORS:
            return jsonify({
                "success": False,
                "error": f"Invalid color. Must be one of: {', '.join(VALID_COLORS)}"
            }), 400
        
        # Update the traffic light state
        traffic_light_state["color"] = color
        traffic_light_state["timestamp"] = datetime.now().isoformat()
        
        return jsonify({
            "color": color,
            "success": True,
            "message": f"Traffic light set to {color}",
            "timestamp": traffic_light_state["timestamp"]
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/traffic-light/colors', methods=['GET'])
def get_valid_colors():
    """Get list of valid traffic light colors"""
    return jsonify({
        "colors": VALID_COLORS,
        "success": True
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000) 