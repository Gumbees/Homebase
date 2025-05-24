document.addEventListener('DOMContentLoaded', function() {
    // --- Element References ---
    const fileInput = document.getElementById('receipt_image');
    const previewContainer = document.getElementById('receipt-preview-container');
    const previewImage = document.getElementById('receipt-preview');
    const ocrExtractBtn = document.getElementById('ocr-extract-btn');
    const ocrAnalyzeBtn = document.getElementById('ocr-analyze-btn');
    const ocrStatusDiv = document.getElementById('ocr-status');
    const modelClaudeRadio = document.getElementById('model_claude');
    const modelOpenAIRadio = document.getElementById('model_openai');
    const dateInput = document.getElementById('date');
    const assetDetailsSection = document.getElementById('asset-details-section');
    const serialNumberInput = document.getElementById('serial_number');
    const quantityInput = document.getElementById('quantity');
    const quantityWarning = document.getElementById('quantityWarning');
    const autoLinkCheck = document.getElementById('auto_link');
    const autoAnalyzeInput = document.getElementById('auto_analyze');
    const lineItemsContainer = document.getElementById('line-items-container');
    const lineItemsList = document.getElementById('line-items-list');
    const lineItemsLoading = document.getElementById('line-items-loading');
    const lineItemsTable = document.getElementById('line-items-table'); // Reference the table itself
    const lineItemsTableBody = lineItemsTable ? lineItemsTable.querySelector('tbody') : null; // Reference tbody
    const receiptForm = document.getElementById('receipt-form');
    const submitBtn = document.getElementById('submit-btn');
    const processingStatus = document.getElementById('processing-status');
    const processingBar = document.getElementById('processing-progress-bar');
    const processingModelText = document.getElementById('processing-model-text');
    const processingStep = document.getElementById('processing-step');
    const statusContainer = document.getElementById('api-status-container'); // Added for checkAPIStatus
    const manualEntryMessage = document.getElementById('manual-entry-message'); // Added for API token errors
    const ocrButtonsContainer = document.getElementById('ocr-buttons-container'); // Added to toggle OCR buttons visibility

    // --- Initialization ---

    // Set default date to today
    if (dateInput && !dateInput.value) { // Only set if no value exists (e.g., from server-side error)
        const today = new Date().toISOString().split('T')[0];
        dateInput.value = today;
    }

    // Check API connection status on page load
    checkAPIStatus();

    // --- Event Listeners ---

    // File Input Change Handler (Preview, Button Enable, and Auto-Analyze)
    if (fileInput) {
        fileInput.addEventListener('change', function(e) {
            handleFileChange();
            
            // Auto-perform OCR analysis when file is selected
            const file = fileInput.files[0];
            if (file && isApiConnected()) {
                // Set a slight delay to allow API status to be checked first
                setTimeout(() => {
                    // Set auto_analyze to true automatically
                    if (autoAnalyzeInput) {
                        autoAnalyzeInput.value = "true";
                    }
                    
                    // First extract basic data
                    handleOcrExtract();
                    
                    // Then do full line item analysis
                    setTimeout(() => {
                        handleOcrAnalyze();
                    }, 500); // Small delay between operations
                }, 300);
            }
        });
    }

    // Serial Number / Quantity Validation Input Handler
    if (serialNumberInput && quantityInput) {
        serialNumberInput.addEventListener('input', validateSerialNumberAndQuantity);
        quantityInput.addEventListener('input', validateSerialNumberAndQuantity);
    }

    // OCR Extract Button Click Handler (kept for manual override)
    if (ocrExtractBtn) {
        ocrExtractBtn.addEventListener('click', handleOcrExtract);
    }

    // OCR Analyze Button Click Handler (kept for manual override)
    if (ocrAnalyzeBtn) {
        ocrAnalyzeBtn.addEventListener('click', handleOcrAnalyze);
    }

    // AI Model Radio Button Change Handler
    if (modelClaudeRadio && modelOpenAIRadio) {
        modelClaudeRadio.addEventListener('change', () => checkAPIStatus('claude'));
        modelOpenAIRadio.addEventListener('change', () => checkAPIStatus('openai'));
    }

    // Form Submission Handler (Validation & Processing Indicator)
    if (receiptForm) {
        receiptForm.addEventListener('submit', handleFormSubmit);
    }

    // --- Functions ---

    // Function to fetch categories for a specific object type
    async function fetchCategoriesForType(objectType) {
        try {
            console.log(`Fetching categories for ${objectType}`);
            const response = await fetch(`/api/categories/${objectType}`);
            
            if (!response.ok) {
                throw new Error(`Failed to fetch categories: ${response.status}`);
            }
            
            const data = await response.json();
            console.log(`Received ${data.categories?.length || 0} categories for ${objectType}`);
            
            if (data.success && data.categories) {
                return data.categories;
            } else {
                console.error('Error fetching categories:', data.error || 'Unknown error');
                return [];
            }
        } catch (error) {
            console.error('Error fetching categories:', error);
            return [];
        }
    }

    // Function to suggest categories for an item using AI
    async function suggestCategoriesForItem(index, description, objectType, amount = null, vendor = null) {
        try {
            const categorySelect = document.getElementById(`category-select-${index}`);
            if (!categorySelect) return;
            
            // Update the select UI to show it's processing
            const currentOptions = Array.from(categorySelect.options);
            categorySelect.innerHTML = '';
            const loadingOption = document.createElement('option');
            loadingOption.value = '';
            loadingOption.textContent = 'AI suggesting categories...';
            categorySelect.appendChild(loadingOption);
            
            // Call the API to get AI-suggested categories
            const response = await fetch('/api/suggest-category', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    description,
                    object_type: objectType,
                    amount,
                    vendor
                })
            });
            
            if (!response.ok) {
                throw new Error(`Failed to suggest categories: ${response.status}`);
            }
            
            const data = await response.json();
            console.log('Category suggestion response:', data);
            
            if (data.success) {
                // Refresh the categories list after suggestions may have created new ones
                await updateCategoriesForRow(index, objectType);
                
                // Check if any categories were created
                if (data.created_categories && data.created_categories.length > 0) {
                    const newCategoryNames = data.created_categories.map(c => c.name).join(', ');
                    console.log(`Created new categories: ${newCategoryNames}`);
                }
                
                // Select the suggested category in the dropdown
                if (data.all_categories && data.all_categories.length > 0) {
                    // Get the top category
                    const topCategory = data.all_categories[0];
                    
                    // Find and select the option with this name
                    const options = Array.from(categorySelect.options);
                    const option = options.find(opt => opt.value.toLowerCase() === topCategory.name.toLowerCase());
                    if (option) {
                        option.selected = true;
                    }
                }
                
                // Return info about what happened
                return {
                    success: true,
                    numSuggested: data.all_categories.length,
                    numCreated: data.created_categories.length
                };
            } else {
                console.error('Error suggesting categories:', data.error || 'Unknown error');
                await updateCategoriesForRow(index, objectType); // Restore normal categories
                return {
                    success: false,
                    error: data.error || 'Unknown error'
                };
            }
        } catch (error) {
            console.error('Error suggesting categories:', error);
            await updateCategoriesForRow(index, objectType); // Restore normal categories
            return {
                success: false,
                error: error.message
            };
        }
    }

    // Handle File Selection Change
    function handleFileChange() {
        const file = fileInput.files[0];
        const hasFile = !!file;

        // Enable/Disable OCR Buttons based on file presence and API connection
        if (ocrExtractBtn) ocrExtractBtn.disabled = !hasFile || !isApiConnected(); 
        if (ocrAnalyzeBtn) ocrAnalyzeBtn.disabled = !hasFile || !isApiConnected();

        // Handle Preview
        if (hasFile && file.type.match('image.*') && previewContainer && previewImage) {
            previewContainer.classList.remove('d-none');
            const reader = new FileReader();
            reader.onload = function(e) {
                previewImage.src = e.target.result;
            };
            reader.readAsDataURL(file);
        } else if (hasFile && (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) && previewContainer && previewImage) {
             // Show PDF icon for PDFs
             previewContainer.classList.remove('d-none');
             previewImage.src = '/static/images/pdf-icon.png'; // Ensure this path is correct
        } else if (previewContainer) {
            // Hide preview if no file or not an image/pdf
            previewContainer.classList.add('d-none');
            if (previewImage) previewImage.src = ''; // Clear src
        }
    }

    // Validate Serial Number and Quantity
    function validateSerialNumberAndQuantity() {
        if (!serialNumberInput || !quantityInput) return true; // Should not happen if called correctly

        const serialNumber = serialNumberInput.value.trim();
        const quantity = parseInt(quantityInput.value, 10);
        let isValid = true;

        if (serialNumber && quantity > 1) {
            if (quantityWarning) quantityWarning.classList.remove('d-none');
            quantityInput.classList.add('is-invalid');
            quantityInput.value = 1; // Force quantity to be 1
            isValid = false;
        } else {
            if (quantityWarning) quantityWarning.classList.add('d-none');
            quantityInput.classList.remove('is-invalid');
        }
        return isValid;
    }

    // Handle Basic OCR Extraction
    function handleOcrExtract() {
        if (!fileInput || !fileInput.files.length) {
            alert('Please select a file first');
            return;
        }
        const file = fileInput.files[0];

        // Show loading state
        ocrExtractBtn.disabled = true;
        ocrExtractBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Processing...';
        if (ocrStatusDiv) {
            ocrStatusDiv.classList.remove('d-none');
            ocrStatusDiv.innerHTML = '<div class="alert alert-info">Extracting data from receipt...</div>';
        }

        const formData = new FormData();
        formData.append('receipt_image', file);
        // Add selected AI model
        const selectedModel = document.querySelector('input[name="ai_model"]:checked');
        if (selectedModel) {
            formData.append('ai_model', selectedModel.value);
        }

        fetch('/api/ocr-receipt', { // Endpoint for basic extraction (might be same as analyze)
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            console.log('OCR Extract result:', data);
            ocrExtractBtn.innerHTML = '<i class="fas fa-magic me-1"></i> Extract Data with OCR';

            if (data.success && data.receipt_data) {
                fillFormFields(data.receipt_data);
                if (ocrStatusDiv) ocrStatusDiv.innerHTML = '<div class="alert alert-success">Receipt data extracted successfully!</div>';
            } else {
                if (ocrStatusDiv) ocrStatusDiv.innerHTML = '<div class="alert alert-danger">Could not extract receipt data: ' + (data.error || 'Unknown error') + '. Please enter details manually.</div>';
                
                // If there was an authentication error, show a helpful message about API keys
                if (data.error_type === 'authentication') {
                    if (ocrStatusDiv) {
                        ocrStatusDiv.innerHTML += '<div class="alert alert-warning mt-2">API authentication failed. Please check your API keys in Settings or continue with manual entry.</div>';
                    }
                }
            }
            handleFileChange(); // Re-evaluate button disabled state based on file presence and API status
        })
        .catch(error => {
            console.error('OCR Extract error:', error);
            ocrExtractBtn.innerHTML = '<i class="fas fa-magic me-1"></i> Extract Data with OCR';

            if (ocrStatusDiv) {
                ocrStatusDiv.classList.remove('d-none');
                ocrStatusDiv.innerHTML = '<div class="alert alert-danger">Error processing receipt. Please try again or enter details manually.</div>';
            }
            handleFileChange(); // Re-evaluate button disabled state
        });
    }

    // Handle Advanced OCR Analysis (with Line Items)
    function handleOcrAnalyze() {
        if (!fileInput || !fileInput.files.length) {
            alert('Please select a file first');
            return;
        }
        const file = fileInput.files[0];

        // Get the selected AI model
        const useClaudeModel = modelClaudeRadio && modelClaudeRadio.checked;
        const modelName = useClaudeModel ? "Claude (Anthropic)" : "GPT-4o (OpenAI)";

        // Show loading state
        ocrAnalyzeBtn.disabled = true;
        ocrAnalyzeBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Analyzing with ' + modelName + '...';
        if (ocrStatusDiv) {
            ocrStatusDiv.classList.remove('d-none');
            ocrStatusDiv.innerHTML = '<div class="alert alert-info">Analyzing receipt with ' + modelName + ' (this may take 10-30 seconds)...</div>';
        }

        // Show line items container with loading indicator
        if (lineItemsContainer) lineItemsContainer.classList.remove('d-none');
        if (lineItemsLoading) lineItemsLoading.classList.remove('d-none');
        if (lineItemsList) lineItemsList.classList.add('d-none');
        if (lineItemsTableBody) lineItemsTableBody.innerHTML = ''; // Clear previous items

        // Set auto_analyze hidden input to true to ensure line items are processed
        if (autoAnalyzeInput) autoAnalyzeInput.value = "true";

        const formData = new FormData();
        formData.append('receipt_image', file);
        formData.append('auto_analyze', 'true'); // Signal backend to do full analysis
        formData.append('auto_link', autoLinkCheck && autoLinkCheck.checked ? 'true' : 'false');
        formData.append('ai_model', useClaudeModel ? 'claude' : 'openai');

        fetch('/api/ocr-receipt', { // Assuming same endpoint handles both basic and analyze
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            console.log('OCR Analyze result:', data);
            ocrAnalyzeBtn.innerHTML = '<i class="fas fa-bolt me-1"></i> Auto-Analyze Line Items';

            if (data.success && data.receipt_data) {
                fillFormFields(data.receipt_data);

                // Fix: Access line_items from receipt_data instead of from top level
                const lineItems = data.receipt_data.line_items || [];
                
                // Render line items
                renderLineItems(lineItems);

                if (lineItemsLoading) lineItemsLoading.classList.add('d-none');
                if (lineItemsList) lineItemsList.classList.remove('d-none');
                if (lineItemsContainer) lineItemsContainer.classList.remove('d-none'); // Ensure container is visible

                if (ocrStatusDiv) ocrStatusDiv.innerHTML = '<div class="alert alert-success">Receipt analyzed successfully!</div>';

            } else {
                // Hide line items container on error
                if (lineItemsContainer) lineItemsContainer.classList.add('d-none');
                if (ocrStatusDiv) ocrStatusDiv.innerHTML = '<div class="alert alert-danger">Could not analyze receipt: ' + (data.error || 'Unknown error') + '. Please enter details manually.</div>';

                // If there was an authentication error, show a helpful message about API keys
                if (data.error_type === 'authentication') {
                    if (ocrStatusDiv) {
                        ocrStatusDiv.innerHTML += '<div class="alert alert-warning mt-2">API authentication failed. Please check your API keys in Settings or continue with manual entry.</div>';
                    }
                }
            }
            handleFileChange(); // Re-evaluate button disabled state
        })
        .catch(error => {
            console.error('OCR Analyze error:', error);
            ocrAnalyzeBtn.innerHTML = '<i class="fas fa-bolt me-1"></i> Auto-Analyze Line Items';

            // Hide line items container on error
            if (lineItemsContainer) lineItemsContainer.classList.add('d-none');

            if (ocrStatusDiv) {
                ocrStatusDiv.classList.remove('d-none');
                ocrStatusDiv.innerHTML = '<div class="alert alert-danger">Error analyzing receipt. Please try again or enter details manually.</div>';
            }
            handleFileChange(); // Re-evaluate button disabled state
        });
    }

    // Fill Form Fields Helper
    function fillFormFields(receiptData) {
        if (!receiptData) return;

        const vendorNameInput = document.getElementById('vendor_name');
        const dateInput = document.getElementById('date');
        const totalAmountInput = document.getElementById('total_amount');
        const descriptionInput = document.getElementById('description');

        if (vendorNameInput) vendorNameInput.value = receiptData.vendor_name || '';
        if (dateInput && receiptData.date) {
             // Ensure YYYY-MM-DD format
             try {
                 dateInput.value = new Date(receiptData.date).toISOString().split('T')[0];
             } catch (e) {
                 console.error("Invalid date format received:", receiptData.date);
             }
        }
        if (totalAmountInput && receiptData.total_amount !== null && receiptData.total_amount !== undefined) {
            totalAmountInput.value = receiptData.total_amount;
        }
        if (descriptionInput) descriptionInput.value = receiptData.description || '';
    }

    // Update Categories for a Row
    async function updateCategoriesForRow(index, objectType, selectedCategory = '') {
        const categorySelect = document.getElementById(`category-select-${index}`);
        if (!categorySelect) return;

        // Clear existing options except the first loading option
        while (categorySelect.options.length > 1) {
            categorySelect.remove(1);
        }
        
        // Update the loading option text
        categorySelect.options[0].text = `Loading ${objectType} categories...`;

        // Fetch categories for the given object type
        const categories = await fetchCategoriesForType(objectType);

        // Clear all options including the loading option
        categorySelect.innerHTML = '';

        // Add a default empty option
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = `-- Select ${objectType} category --`;
        categorySelect.appendChild(defaultOption);

        // Add an option to create a new category
        const createOption = document.createElement('option');
        createOption.value = 'create_new';
        createOption.textContent = '+ Create new category';
        createOption.className = 'text-success';
        categorySelect.appendChild(createOption);

        if (categories.length === 0) {
            defaultOption.textContent = `No categories found for ${objectType}`;
            return;
        }

        // Populate the dropdown with fetched categories
        categories.forEach(category => {
            const option = document.createElement('option');
            option.value = category.name;
            option.textContent = category.name;
            
            // Add data attributes for additional category info
            option.dataset.description = category.description || '';
            option.dataset.icon = category.icon || '';
            option.dataset.color = category.color || '';
            
            // Select this option if it matches the provided selectedCategory
            if (selectedCategory && category.name.toLowerCase() === selectedCategory.toLowerCase()) {
                option.selected = true;
            }
            
            categorySelect.appendChild(option);
        });
        
        // Add event listener for "Create new category" option
        categorySelect.addEventListener('change', function() {
            if (this.value === 'create_new') {
                // Reset selection to the default option
                this.value = '';
                
                // Here we could show a modal/form to create a new category
                // For now, just alert the user
                alert('Creating new categories directly from this screen is not yet implemented. Please use the Object Form to create new categories.');
            }
        });
    }

    // Render Line Items Function
    function renderLineItems(items) {
        if (!lineItemsTableBody) return; // Exit if table body doesn't exist

        lineItemsTableBody.innerHTML = ''; // Clear existing rows

        if (!items || items.length === 0) {
            lineItemsTableBody.innerHTML = '<tr><td colspan="7"><div class="alert alert-warning text-center">No line items found or extracted.</div></td></tr>';
            return;
        }

        const types = ['asset', 'consumable', 'component', 'service', 'software', 'other'];

        items.forEach((item, index) => {
            // Sanitize and format data
            const description = (item.description || 'Unknown item').replace(/"/g, '&quot;');
            const quantity = parseInt(item.quantity || 1);
            const unitPrice = parseFloat(item.unit_price || 0).toFixed(2);
            const totalPrice = parseFloat(item.total_price || (quantity * parseFloat(unitPrice))).toFixed(2);
            const suggestedType = item.object_type || 'consumable'; // Default type
            const suggestedCategory = item.category || '';
            const vendor = document.getElementById('vendor_name')?.value || '';

            const row = lineItemsTableBody.insertRow();

            // 1. Create Object Checkbox Cell
            const checkCell = row.insertCell();
            checkCell.className = 'text-center align-middle';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'form-check-input line-item-checkbox';
            checkbox.checked = true; // Default to checked
            checkbox.name = 'line_items[' + index + '][create_object]';
            checkbox.value = 'true';
            checkCell.appendChild(checkbox);

            // 2. Description Cell (Readonly)
            const descCell = row.insertCell();
            descCell.className = 'align-middle';
            descCell.textContent = description;

            // 3. Qty Cell (Readonly)
            const qtyCell = row.insertCell();
            qtyCell.className = 'text-end align-middle';
            qtyCell.textContent = quantity;

            // 4. Unit Price Cell (Readonly)
            const unitPriceCell = row.insertCell();
            unitPriceCell.className = 'text-end align-middle';
            unitPriceCell.textContent = '$' + unitPrice;

            // 5. Total Price Cell (Readonly)
            const totalPriceCell = row.insertCell();
            totalPriceCell.className = 'text-end align-middle';
            totalPriceCell.textContent = '$' + totalPrice;

            // 6. Object Type Select Cell
            const typeCell = row.insertCell();
            typeCell.className = 'align-middle';
            const typeSelect = document.createElement('select');
            typeSelect.className = 'form-select form-select-sm line-item-type';
            typeSelect.name = 'line_items[' + index + '][object_type]';
            typeSelect.dataset.index = index;
            types.forEach(type => {
                const option = document.createElement('option');
                option.value = type;
                option.textContent = type.charAt(0).toUpperCase() + type.slice(1);
                option.selected = (type === suggestedType);
                typeSelect.appendChild(option);
            });
            typeCell.appendChild(typeSelect);
            
            // 7. Category Cell
            const categoryCell = row.insertCell();
            categoryCell.className = 'align-middle d-flex align-items-center';
            
            // Create category select
            const categorySelect = document.createElement('select');
            categorySelect.className = 'form-select form-select-sm line-item-category';
            categorySelect.name = 'line_items[' + index + '][category]';
            categorySelect.id = `category-select-${index}`;
            
            // Create magic button for AI suggestion
            const magicBtn = document.createElement('button');
            magicBtn.type = 'button';
            magicBtn.className = 'btn btn-sm btn-outline-info ms-1';
            magicBtn.title = 'Suggest categories with AI';
            magicBtn.innerHTML = '<i class="fas fa-magic"></i>';
            
            // Create a container div to hold both select and button
            const categoryContainer = document.createElement('div');
            categoryContainer.className = 'd-flex';
            categoryContainer.style.width = '100%';
            
            // Add a loading option while we fetch categories
            const loadingOption = document.createElement('option');
            loadingOption.value = '';
            loadingOption.textContent = 'Loading categories...';
            categorySelect.appendChild(loadingOption);
            
            categoryContainer.appendChild(categorySelect);
            categoryContainer.appendChild(magicBtn);
            categoryCell.appendChild(categoryContainer);
            
            // Fetch categories for the selected object type
            updateCategoriesForRow(index, suggestedType, suggestedCategory);
            
            // Add event listener to update categories when object type changes
            typeSelect.addEventListener('change', function() {
                const newType = this.value;
                const rowIndex = parseInt(this.dataset.index);
                updateCategoriesForRow(rowIndex, newType);
            });
            
            // Add event listener for magic button to suggest categories
            magicBtn.addEventListener('click', async function() {
                const rowIndex = index;
                const itemDesc = description;
                const objType = typeSelect.value;
                
                // Disable button while processing
                this.disabled = true;
                this.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
                
                // Call the AI to suggest categories
                const result = await suggestCategoriesForItem(rowIndex, itemDesc, objType, totalPrice, vendor);
                
                // Re-enable button
                this.disabled = false;
                this.innerHTML = '<i class="fas fa-magic"></i>';
                
                // Show feedback if categories were created
                if (result.success && result.numCreated > 0) {
                    // Flash the select with a success color
                    categorySelect.classList.add('border-success');
                    setTimeout(() => {
                        categorySelect.classList.remove('border-success');
                    }, 3000);
                } else if (!result.success) {
                    console.error('Failed to suggest categories:', result.error);
                }
            });

            // Add hidden inputs for submission (needed because table cells are readonly)
            function addHiddenInput(name, value) {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = name;
                input.value = value;
                row.appendChild(input); // Append directly to the row
            }

            addHiddenInput('line_items[' + index + '][description]', description);
            addHiddenInput('line_items[' + index + '][quantity]', quantity);
            addHiddenInput('line_items[' + index + '][unit_price]', unitPrice);
            addHiddenInput('line_items[' + index + '][total_price]', totalPrice);
            
            // Auto-suggest categories initially if we have both object type and description
            if (suggestedType && description) {
                // Slight delay to ensure the UI is responsive first
                setTimeout(() => {
                    suggestCategoriesForItem(index, description, suggestedType, totalPrice, vendor);
                }, 100 * (index + 1)); // Stagger the requests to avoid overloading the API
            }
        });
    }

    // Handle Form Submission
    function handleFormSubmit(e) {
        // Basic required field validation
        const vendorName = document.getElementById('vendor_name').value.trim();
        const date = dateInput ? dateInput.value.trim() : '';
        const totalAmount = document.getElementById('total_amount').value.trim();
        const file = fileInput ? fileInput.files[0] : null;

        let missingFields = [];
        if (!vendorName) missingFields.push('Vendor Name');
        if (!date) missingFields.push('Date');
        if (!totalAmount) missingFields.push('Total Amount');
        if (!file) missingFields.push('Receipt File');

        if (missingFields.length > 0) {
            e.preventDefault();
            alert('Please fill in all required fields:\n- ' + missingFields.join('\n- '));
            return false;
        }

        // Validate serial number and quantity
        if (serialNumberInput && quantityInput) {
            if (!validateSerialNumberAndQuantity()) {
                e.preventDefault();
                e.stopPropagation();
                alert('Assets with serial numbers must have a quantity of 1.');
                return false;
            }
        }

        // Always set auto_analyze to true on submission to ensure line items are processed
        if (autoAnalyzeInput) {
            autoAnalyzeInput.value = "true";
        }

        // Show processing indicator
        if (submitBtn) {
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Processing...';
            submitBtn.disabled = true;
        }
        
        // Instead of disabling the inputs (which prevents their values from being submitted),
        // just make them appear disabled but don't actually disable them
        const formInputs = receiptForm.querySelectorAll('input:not([type=file]), select, textarea, button:not([type=submit])');
        formInputs.forEach(input => { 
            // Save original state
            input.dataset.originalPointerEvents = input.style.pointerEvents;
            input.dataset.originalOpacity = input.style.opacity;
            
            // Make them appear disabled visually
            input.style.pointerEvents = 'none';
            input.style.opacity = '0.65';
        });

        // Show detailed processing status
        if (processingStatus) {
            processingStatus.classList.remove('d-none');
            const useClaudeModel = modelClaudeRadio && modelClaudeRadio.checked;
            const modelName = useClaudeModel ? "Claude" : "GPT-4o";
            if (processingModelText) processingModelText.textContent = 'Processing receipt with ' + modelName + '... This may take up to 60 seconds.';

            let progress = 0;
            const progressInterval = setInterval(() => {
                if (progress < 95) {
                    progress += (progress < 30 ? 1 : (progress < 60 ? 0.5 : 0.25));
                    if (processingBar) {
                        processingBar.style.width = progress + '%';
                        processingBar.setAttribute('aria-valuenow', progress);
                    }
                    if (processingStep) {
                         const isPdf = file && (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'));
                         if (progress < 15) processingStep.textContent = isPdf ? "Preparing document..." : "Preparing image...";
                         else if (progress < 35) processingStep.textContent = "Extracting data...";
                         else if (progress < 75) processingStep.textContent = "Analyzing content...";
                         else processingStep.textContent = "Finalizing...";
                    }
                } else {
                     clearInterval(progressInterval); // Stop interval near end
                }
            }, 500);
            processingStatus.dataset.progressInterval = progressInterval; // Store interval ID if needed
        }

        // Let the form submit naturally
        return true;
    }

    // --- API Status Check ---
    let currentApiStatus = { claude: false, openai: false }; // Simple state to track connectivity

    function isApiConnected() {
        const selectedModel = modelClaudeRadio && modelClaudeRadio.checked ? 'claude' : 'openai';
        return currentApiStatus[selectedModel];
    }

    function checkAPIStatus(specificModel = null) {
        let modelToCheck = specificModel;
        if (!modelToCheck) {
            modelToCheck = modelClaudeRadio && modelClaudeRadio.checked ? 'claude' : 'openai';
        }

        if (statusContainer) {
            // Restore DOM manipulation for 'Checking...'
            statusContainer.innerHTML = ''; // Clear previous status

            const alertDiv = document.createElement('div');
            alertDiv.className = 'alert alert-info py-1 small';

            const spinnerSpan = document.createElement('span');
            spinnerSpan.className = 'spinner-border spinner-border-sm me-1';
            spinnerSpan.setAttribute('role', 'status');
            spinnerSpan.setAttribute('aria-hidden', 'true');
            alertDiv.appendChild(spinnerSpan);

            const modelText = modelToCheck === 'claude' ? 'Claude' : 'OpenAI';
            // Use simple string concatenation for the text node
            const textNode = document.createTextNode(' Checking ' + modelText + ' API connection...');
            alertDiv.appendChild(textNode);
            statusContainer.appendChild(alertDiv);
        }

        // Disable buttons while checking
        if (ocrExtractBtn) ocrExtractBtn.disabled = true;
        if (ocrAnalyzeBtn) ocrAnalyzeBtn.disabled = true;

        fetch('/api/check-api-connection?model=' + modelToCheck)
            .then(response => response.json())
            .then(data => {
                currentApiStatus[modelToCheck] = data.success; // Update status

                if (statusContainer) {
                    statusContainer.innerHTML = ''; // Clear checking message
                    const modelText = modelToCheck === 'claude' ? 'Claude' : 'OpenAI';

                    if (data.success) {
                        // Create success message elements
                        const successDiv = document.createElement('div');
                        successDiv.className = 'alert alert-success py-1 small';
                        const icon = document.createElement('i');
                        icon.className = 'fas fa-check-circle me-1';
                        successDiv.appendChild(icon);
                        successDiv.appendChild(document.createTextNode(' ' + modelText + ' API is connected.'));
                        statusContainer.appendChild(successDiv);
                        
                        // Show OCR buttons when API is connected
                        if (ocrButtonsContainer) ocrButtonsContainer.classList.remove('d-none');
                        if (manualEntryMessage) manualEntryMessage.classList.add('d-none');
                        
                    } else {
                        // Create error message elements
                        const errorDiv = document.createElement('div');
                        errorDiv.className = 'alert alert-danger py-1 small';
                        const icon = document.createElement('i');
                        icon.className = 'fas fa-exclamation-triangle me-1';
                        errorDiv.appendChild(icon);
                        errorDiv.appendChild(document.createTextNode(' ' + modelText + ' API Error: ' + (data.message || 'Connection failed')));
                        statusContainer.appendChild(errorDiv);

                        // Handle authentication errors specifically
                        if (data.error_type === 'authentication') {
                            const authWarningDiv = document.createElement('div');
                            authWarningDiv.className = 'alert alert-warning py-1 small mt-1';
                            authWarningDiv.textContent = 'Missing or invalid API key. Please check configuration.';
                            statusContainer.appendChild(authWarningDiv);
                            
                            // Hide OCR buttons and show manual entry message
                            if (ocrButtonsContainer) ocrButtonsContainer.classList.add('d-none');
                            if (manualEntryMessage) {
                                manualEntryMessage.classList.remove('d-none');
                                manualEntryMessage.innerHTML = '<div class="alert alert-info">OCR features are disabled due to API key issues. Please enter receipt details manually or update API keys in Settings.</div>';
                            }
                        }
                    }
                }
                // Re-evaluate button states after check
                handleFileChange();
            })
            .catch(error => {
                currentApiStatus[modelToCheck] = false; // Assume failure on fetch error
                console.error('API Status Check Error:', error);
                if (statusContainer) {
                    statusContainer.innerHTML = ''; // Clear checking message
                    // Create fetch error message elements
                    const fetchErrorDiv = document.createElement('div');
                    fetchErrorDiv.className = 'alert alert-danger py-1 small';
                    const icon = document.createElement('i');
                    icon.className = 'fas fa-exclamation-circle me-1';
                    fetchErrorDiv.appendChild(icon);
                    fetchErrorDiv.appendChild(document.createTextNode(' Error checking API status: ' + error.message));
                    statusContainer.appendChild(fetchErrorDiv);
                    
                    // Hide OCR buttons and show manual entry message
                    if (ocrButtonsContainer) ocrButtonsContainer.classList.add('d-none');
                    if (manualEntryMessage) {
                        manualEntryMessage.classList.remove('d-none');
                        manualEntryMessage.innerHTML = '<div class="alert alert-info">OCR features are unavailable. Please enter receipt details manually.</div>';
                    }
                }
                // Re-evaluate button states after check
                handleFileChange();
            });
    }
}); // End DOMContentLoaded
