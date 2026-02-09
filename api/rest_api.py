"""
Flask API for ML model serving.
Clean separation of concerns with dedicated modules for lifecycle, registry, and sync.
"""
from flask import Flask, request, jsonify, Response, render_template
import os
import signal
import sys
import json
import logging

# Local imports - new modular structure
from api.model_registry import get_registry
from api.model_lifecycle import get_lifecycle_manager
from api.webhook_handler import get_webhook_handler
from api.filesystem_watcher import get_filesystem_monitor
from api.github_client import list_github_models
import model_handlers.model_detector as model_detector
from utils import send_message_to_prediction_destination
from messaging.kafka_consumer import start_kafka_consumer, stop_kafka_consumer
from messaging.mqtt_consumer import start_mqtt_consumer, stop_mqtt_consumer
import tf_serving_manager

# Configuration
API_HOST = os.getenv("API_HOST", "localhost")
PORT = int(os.getenv("PORT", "8086"))
MODEL_SOURCE = os.getenv("MODEL_SOURCE", "local_filesystem")
GITHUB_REPO = os.getenv("GITHUB_REPO", "apnevma/models-to-test")
PREDICTION_DESTINATION = os.getenv("PREDICTION_DESTINATION", "kafka")
INPUT_DATA_SOURCE = os.getenv("INPUT_DATA_SOURCE", "kafka")
MODELS_PATH = os.getenv("MODELS_PATH", "/models")

if PREDICTION_DESTINATION == "kafka":
    KAFKA_OUTPUT_TOPIC = os.getenv("KAFKA_OUTPUT_TOPIC", "INTRA_test_topic1")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get the project root directory (parent of api/)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Initialize Flask app with explicit paths
app = Flask(__name__,
            template_folder=os.path.join(project_root, 'templates'),
            static_folder=os.path.join(project_root, 'static'))
api_url = f"http://{API_HOST}:{PORT}"

# Get singleton instances
registry = get_registry()
lifecycle_manager = get_lifecycle_manager(MODELS_PATH)
webhook_handler = get_webhook_handler()


# ============================================================================
# INITIALIZATION
# ============================================================================

def initialize_models():
    """Initialize the model registry from the configured source."""
    registry.clear_all()
    
    if MODEL_SOURCE == "github":
        _initialize_from_github()
    else:
        _initialize_from_filesystem()


def _initialize_from_github():
    """Load models from GitHub repository."""
    try:
        github_entries = list_github_models()
        for model_name, entry in github_entries.items():
            registry.register_model(model_name, entry)
        logger.info(f"[INIT] Loaded {len(github_entries)} models from GitHub")
    except Exception as e:
        logger.error(f"[INIT] Failed to list GitHub models: {e}")


def _initialize_from_filesystem():
    """Load models from local filesystem."""
    if not os.path.exists(MODELS_PATH):
        logger.warning(f"[INIT] Models path does not exist: {MODELS_PATH}")
        return
    
    for filename in os.listdir(MODELS_PATH):
        file_path = os.path.join(MODELS_PATH, filename)
        if os.path.isdir(file_path) or os.path.isfile(file_path):
            model_name = os.path.splitext(filename)[0]
            metadata = {
                "source": "local_filesystem",
                "model_name": model_name,
                "model_path": file_path
            }
            registry.register_model(model_name, metadata)
    
    logger.info(f"[INIT] Loaded {len(registry.list_available_models())} models from filesystem")


# ============================================================================
# API ENDPOINTS - Model Management
# ============================================================================

@app.route('/models', methods=['GET'])
def list_models():
    """List all available models with their status."""
    available = registry.list_available_models()
    active_models_dict = registry.list_active_models()
    
    output = []
    for model_name, metadata in available.items():
        is_active = model_name in active_models_dict
        
        model_entry = {
            "model_name": model_name,
            "status": "active" if is_active else "inactive",
            "model_path": metadata.get("model_path"),
            "source": metadata.get("source", "unknown"),
            "predict_url": f"http://{API_HOST}:{PORT}/predict/{model_name}" if is_active else None
        }
        
        # Include model_info for active models
        if is_active:
            active_data = active_models_dict[model_name]
            model_entry["model_info"] = active_data.get("model_info", {})
        
        output.append(model_entry)
    
    return jsonify(output)


@app.route('/status/<model_name>')
def model_status(model_name):
    """Get the status of a specific model."""
    if not registry.is_available(model_name):
        return jsonify({"error": "Model not found"}), 404
    
    return jsonify({
        "model_name": model_name,
        "active": registry.is_active(model_name)
    })


@app.route('/activate/<model_name>', methods=['POST'])
def activate_model(model_name):
    """Activate a model to make it available for predictions."""
    success, message, model_data = lifecycle_manager.activate_model(model_name)
    
    if not success:
        return jsonify({"error": message}), 400
    
    return jsonify({
        "message": message,
        "predict_endpoint": f"/predict/{model_name}"
    })


@app.route('/deactivate/<model_name>', methods=['POST'])
def deactivate_model(model_name):
    """Deactivate a model to stop serving predictions."""
    success, message = lifecycle_manager.deactivate_model(model_name)
    
    return jsonify({"message": message})


# ============================================================================
# API ENDPOINTS - Predictions
# ============================================================================

@app.route("/predict/<model_name>", methods=["POST"])
def predict(model_name):
    """Make a prediction using the specified active model."""
    active_model = registry.get_active_model(model_name)
    
    if not active_model:
        return jsonify({"error": f"Model '{model_name}' not active"}), 404
    
    payload = request.get_json(silent=True) or {}
    features = payload.get("input")
    
    try:
        result = model_detector.predict(
            active_model["model_path"],
            active_model["model"],
            features
        )
        
        # Unwrap TF Serving result if needed
        if isinstance(result, dict) and "predictions" in result:
            result = result["predictions"]
        
        response_payload = {
            "model": model_name,
            "status": "success",
            "prediction": result
        }
        
        if not send_message_to_prediction_destination(response_payload, model_name):
            return jsonify({"error": "Failed to forward prediction"}), 500
        
        return jsonify({
            "status": "sent",
            "destination": PREDICTION_DESTINATION,
            "prediction": result
        })
    
    except Exception as e:
        error_message = {
            "model": model_name,
            "status": "error",
            "error": str(e),
            "expected_input": active_model["model_info"]
        }
        
        send_message_to_prediction_destination(error_message, model_name)
        return jsonify(error_message), 400


# ============================================================================
# API ENDPOINTS - Webhooks
# ============================================================================

@app.route('/github/webhook', methods=["POST"])
def github_webhook():
    """Handle GitHub webhook events."""
    event = request.headers.get("X-GitHub-Event")
    
    if event == "ping":
        logger.info("[WEBHOOK] Ping received")
        return jsonify({"status": "pong"}), 200
    
    if event != "push":
        logger.info(f"[WEBHOOK] Received {event} event")
        return jsonify({"status": f"received {event}"}), 200
    
    # Process push event
    payload = request.get_json()
    webhook_handler.handle_push_event(payload, branch_filter="refs/heads/main")
    
    return jsonify({"status": "processed"}), 200


# ============================================================================
# API ENDPOINTS - Help & Info
# ============================================================================

@app.route('/test')
def test_endpoint():
    """Health check endpoint."""
    return 'The Model Server is ALIVE!'


@app.route('/help')
def help_endpoint():
    """Provide information about active models and their endpoints."""
    active_models = registry.list_active_models()
    
    if not active_models:
        return jsonify({"message": "No models currently active."})
    
    response_data = {
        "message": (
            "Below are all the active models. "
            "To add new models, add them to the repository and they will be "
            "automatically detected. Use /activate/<model_name> to activate them."
        ),
        "active_models": [
            {
                "model_name": info["model_name"],
                "endpoint_url": f"http://{API_HOST}:{PORT}/predict/{info['model_name']}",
                "model_info": info["model_info"]
            }
            for info in active_models.values()
        ]
    }
    
    return Response(
        json.dumps(response_data, indent=4),
        content_type="application/json"
    )


@app.route('/ui')
def models_ui():
    all_models = registry.list_available_models()
    active_models = registry.list_active_models()
    
    models_data = []
    for model_name, metadata in all_models.items():
        is_active = model_name in active_models
        
        model_entry = {
            "model_name": model_name,
            "is_active": is_active,
            "model_path": metadata.get("model_path"),
            "source": metadata.get("source"),
        }
        
        # If active, include runtime info
        if is_active:
            active_data = active_models[model_name]
            model_entry["model_info"] = active_data["model_info"]
            model_entry["endpoint_url"] = f"{api_url}/predict/{model_name}"
        
        models_data.append(model_entry)

    # Sort: active models first, then alphabetically
    models_data.sort(key=lambda m: (not m["is_active"], m["model_name"]))
    
    return render_template(
        'models_ui.html',
        models=models_data,
        api_url=api_url,
        model_source=MODEL_SOURCE,
        github_repo=GITHUB_REPO
    )


# ============================================================================
# LIFECYCLE MANAGEMENT
# ============================================================================

def cleanup(signum, frame):
    """Cleanup handler for graceful shutdown."""
    logger.info("[SHUTDOWN] Starting cleanup...")
    
    # Stop messaging consumers
    if INPUT_DATA_SOURCE == "kafka":
        try:
            stop_kafka_consumer()
            logger.info("[SHUTDOWN] Kafka consumer stopped")
        except Exception as e:
            logger.error(f"[SHUTDOWN] Failed to stop Kafka consumer: {e}")
    elif INPUT_DATA_SOURCE == "mqtt":
        try:
            stop_mqtt_consumer()
            logger.info("[SHUTDOWN] MQTT consumer stopped")
        except Exception as e:
            logger.error(f"[SHUTDOWN] Failed to stop MQTT consumer: {e}")
    
    # Stop all TF Serving containers
    logger.info("[SHUTDOWN] Stopping TF Serving containers...")
    for container in tf_serving_manager.list_managed_containers():
        try:
            container.remove(force=True)
            logger.info(f"[SHUTDOWN] Stopped {container.name}")
        except Exception as e:
            logger.error(f"[SHUTDOWN] Failed to stop {container.name}: {e}")
    
    logger.info("[SHUTDOWN] Cleanup complete")
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    logger.info(f"[STARTUP] Starting ML Model Serving Tool")
    logger.info(f"[STARTUP] Model source: {MODEL_SOURCE}")
    logger.info(f"[STARTUP] Models path: {MODELS_PATH}")
    
    # Initialize model registry
    initialize_models()
    
    # Start filesystem monitoring (if using local models)
    if MODEL_SOURCE == "local_filesystem":
        fs_monitor = get_filesystem_monitor(MODELS_PATH)
        fs_monitor.start()
    
    # Start messaging consumers
    if INPUT_DATA_SOURCE == "kafka":
        start_kafka_consumer()
        logger.info("[STARTUP] Kafka consumer started")
    elif INPUT_DATA_SOURCE == "mqtt":
        start_mqtt_consumer()
        logger.info("[STARTUP] MQTT consumer started")
    
    # Start Flask server
    logger.info(f"[STARTUP] Starting Flask server on {API_HOST}:{PORT}")
    app.run(host='0.0.0.0', port=PORT)
