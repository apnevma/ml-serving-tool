// Models UI - Interactive model management
(function() {
  'use strict';

  // Toast instances
  let successToast, errorToast;

  // Initialize on DOM ready
  document.addEventListener('DOMContentLoaded', function() {
    initializeToasts();
    attachEventListeners();
  });

  // Initialize Bootstrap toasts
  function initializeToasts() {
    const successToastEl = document.getElementById('successToast');
    const errorToastEl = document.getElementById('errorToast');
    
    successToast = new bootstrap.Toast(successToastEl, { delay: 3000 });
    errorToast = new bootstrap.Toast(errorToastEl, { delay: 5000 });
  }

  // Attach event listeners using event delegation
  function attachEventListeners() {
    const container = document.getElementById('modelsContainer');
    
    if (!container) return;

    // Handle activate button clicks
    container.addEventListener('click', function(e) {
      if (e.target.closest('.activate-btn')) {
        const btn = e.target.closest('.activate-btn');
        const modelName = btn.dataset.modelName;
        handleActivate(modelName, btn);
      }
    });

    // Handle deactivate button clicks
    container.addEventListener('click', function(e) {
      if (e.target.closest('.deactivate-btn')) {
        const btn = e.target.closest('.deactivate-btn');
        const modelName = btn.dataset.modelName;
        handleDeactivate(modelName, btn);
      }
    });

    // Handle flip button clicks
    container.addEventListener('click', function(e) {
      if (e.target.closest('.flip-btn')) {
        const btn = e.target.closest('.flip-btn');
        const cardInner = btn.closest('.flip-card').querySelector('.flip-card-inner');
        cardInner.classList.toggle('flipped');
      }
    });
  }

  // Handle model activation
  async function handleActivate(modelName, button) {
    const wrapper = document.querySelector(`[data-model-name="${modelName}"]`);
    
    // Set loading state
    setButtonLoading(button, true);
    
    try {
      const response = await fetch(`/activate/${modelName}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to activate model');
      }

      // Success! Now fetch the updated model info
      await refreshModelCard(modelName, wrapper);
      showToast('success', `Model "${modelName}" activated successfully!`);

    } catch (error) {
      console.error('Activation error:', error);
      showToast('error', `Failed to activate "${modelName}": ${error.message}`);
      setButtonLoading(button, false);
    }
  }

  // Handle model deactivation
  async function handleDeactivate(modelName, button) {
    const wrapper = document.querySelector(`[data-model-name="${modelName}"]`);
    
    // Set loading state
    setButtonLoading(button, true);
    
    try {
      const response = await fetch(`/deactivate/${modelName}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to deactivate model');
      }

      // Success! Transform card back to inactive state
      await refreshModelCard(modelName, wrapper);
      showToast('success', `Model "${modelName}" deactivated successfully!`);

    } catch (error) {
      console.error('Deactivation error:', error);
      showToast('error', `Failed to deactivate "${modelName}": ${error.message}`);
      setButtonLoading(button, false);
    }
  }

  // Refresh a single model card by fetching current state
  async function refreshModelCard(modelName, wrapper) {
    try {
      // Fetch current status
      const response = await fetch(`/status/${modelName}`);
      const statusData = await response.json();

      if (!response.ok) {
        throw new Error('Failed to fetch model status');
      }

      const isActive = statusData.active;

      // If state changed, rebuild the card
      const currentIsActive = wrapper.dataset.isActive === 'true';
      
      if (isActive !== currentIsActive) {
        // Fetch full model list to get complete info
        const modelsResponse = await fetch('/models');
        const models = await modelsResponse.json();
        const modelData = models.find(m => m.model_name === modelName);

        if (modelData) {
          rebuildCard(wrapper, modelData);
        }
      }

    } catch (error) {
      console.error('Error refreshing card:', error);
      throw error;
    }
  }

  // Rebuild a model card with new state
  function rebuildCard(wrapper, modelData) {
    const isActive = modelData.status === 'active';
    const modelName = modelData.model_name;

    // Add animation class
    wrapper.classList.add('animating');
    setTimeout(() => wrapper.classList.remove('animating'), 300);

    // Update data attribute
    wrapper.dataset.isActive = isActive;

    if (isActive) {
      // Build active flip card
      wrapper.innerHTML = buildActiveCard(modelData);
    } else {
      // Build inactive simple card
      wrapper.innerHTML = buildInactiveCard(modelData);
    }
  }

  // Build HTML for active model card
  function buildActiveCard(model) {
    // Note: We need to fetch model_info from somewhere or pass it
    // For now, we'll make another API call to get the full details
    // Alternatively, enhance the /status endpoint to return model_info
    
    return `
      <div class="flip-card active-model">
        <div class="flip-card-inner">
          <!-- FRONT -->
          <div class="flip-card-front card shadow-sm border-success border-2">
            <div class="card-body d-flex flex-column justify-content-center text-center">
              <div class="status-badge badge bg-success mb-2">
                <i class="bi bi-check-circle-fill me-1"></i>Active
              </div>
              <h5 class="card-title fw-bold mb-2">${model.model_name}</h5>
              <p class="card-text mb-1"><strong>Type:</strong> Loading...</p>
              <p class="card-text mb-0">
                <strong>Endpoint:</strong><br>
                <code class="text-success">${model.predict_url || '/predict/' + model.model_name}</code>
              </p>
              <div class="mt-3">
                <button class="btn btn-outline-primary btn-sm flip-btn">
                  <i class="bi bi-info-circle me-1"></i>More Info
                </button>
                <button class="btn btn-outline-danger btn-sm deactivate-btn" data-model-name="${model.model_name}">
                  <i class="bi bi-x-circle me-1"></i>Deactivate
                </button>
              </div>
            </div>
          </div>
          <!-- BACK -->
          <div class="flip-card-back card shadow-sm border-success border-2">
            <div class="card-body overflow-auto">
              <h6 class="fw-bold text-center text-success mb-3">Model Details</h6>
              <pre class="small text-start bg-light p-2 rounded model-info-json">Loading model information...</pre>
              <button class="btn btn-outline-secondary btn-sm w-100 mt-2 flip-btn">
                <i class="bi bi-arrow-left me-1"></i>Back
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // Build HTML for inactive model card
  function buildInactiveCard(model) {
    return `
      <div class="simple-card inactive-model">
        <div class="card shadow-sm border-secondary border-1">
          <div class="card-body d-flex flex-column justify-content-center text-center">
            <div class="status-badge badge bg-secondary mb-2">
              <i class="bi bi-dash-circle me-1"></i>Inactive
            </div>
            <h5 class="card-title fw-bold mb-2 text-muted">${model.model_name}</h5>
            <p class="card-text text-muted mb-1">
              <small><strong>Source:</strong> ${model.source || 'unknown'}</small>
            </p>
            <p class="card-text text-muted mb-3">
              <small><strong>Path:</strong> ${model.model_path || 'N/A'}</small>
            </p>
            <button class="btn btn-primary activate-btn" data-model-name="${model.model_name}">
              <i class="bi bi-play-circle me-1"></i>Activate
            </button>
          </div>
        </div>
      </div>
    `;
  }

  // Set button loading state
  function setButtonLoading(button, isLoading) {
    if (isLoading) {
      button.disabled = true;
      button.dataset.originalText = button.innerHTML;
      button.innerHTML = `
        <span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>
        Loading...
      `;
    } else {
      button.disabled = false;
      if (button.dataset.originalText) {
        button.innerHTML = button.dataset.originalText;
      }
    }
  }

  // Show toast notification
  function showToast(type, message) {
    if (type === 'success') {
      document.getElementById('successMessage').textContent = message;
      successToast.show();
    } else if (type === 'error') {
      document.getElementById('errorMessage').textContent = message;
      errorToast.show();
    }
  }

})();
