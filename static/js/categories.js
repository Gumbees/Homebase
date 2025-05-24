/**
 * Categories.js - Handles dynamic loading and management of categories
 * based on object types
 */

document.addEventListener('DOMContentLoaded', function() {
    // Get the object type selector and category selector elements
    const objectTypeSelect = document.getElementById('object-type') || 
                             document.getElementById('object_type') || 
                             document.getElementById('object-type-select');
    const categorySelect = document.getElementById('categories');
    
    // If both elements exist, set up the dynamic loading
    if (objectTypeSelect && categorySelect) {
        console.log('Categories.js: Found object type selector and category selector');
        console.log('Object type:', objectTypeSelect.id, 'Value:', objectTypeSelect.value);
        
        // Initial load of categories based on the default selected object type
        loadCategoriesForType(objectTypeSelect.value);
        
        // Add event listener for when the object type changes
        objectTypeSelect.addEventListener('change', function() {
            console.log('Object type changed to:', this.value);
            loadCategoriesForType(this.value);
        });
        
        // Add event listener for when selections change to update preview
        categorySelect.addEventListener('change', updateCategoryPreview);
    } else {
        console.warn('Categories.js: Could not find required elements:');
        console.warn('Object type selector found:', !!objectTypeSelect);
        console.warn('Category selector found:', !!categorySelect);
    }
    
    // Function to update the category preview
    function updateCategoryPreview() {
        const previewArea = document.getElementById('category-preview');
        if (!previewArea || !categorySelect) return;
        
        // Clear the preview area
        previewArea.innerHTML = '';
        previewArea.classList.remove('d-none');
        
        // Get all selected options
        const selectedOptions = Array.from(categorySelect.selectedOptions);
        
        if (selectedOptions.length === 0) {
            previewArea.classList.add('d-none');
            return;
        }
        
        // Create badges for each selected category
        selectedOptions.forEach(option => {
            const badge = document.createElement('span');
            badge.className = 'badge bg-primary me-1 mb-1';
            
            // Add icon if available
            const icon = option.dataset.icon;
            if (icon) {
                const iconElement = document.createElement('i');
                iconElement.className = `fas fa-${icon} me-1`;
                badge.appendChild(iconElement);
            }
            
            badge.appendChild(document.createTextNode(option.textContent));
            previewArea.appendChild(badge);
        });
    }
    
    // Function to load categories for a specific object type
    function loadCategoriesForType(objectType) {
        if (!objectType) {
            console.warn('Cannot load categories: no object type provided');
            return;
        }
        
        console.log(`Loading categories for object type: ${objectType}`);
        
        // Show loading indicator in the category dropdown
        categorySelect.innerHTML = '<option value="">Loading categories...</option>';
        
        // Fetch categories for this object type from the API
        const apiUrl = `/api/categories/${objectType}`;
        console.log(`Fetching from: ${apiUrl}`);
        fetch(apiUrl)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                // Clear the loading message
                categorySelect.innerHTML = '';
                
                // Add the default empty option
                const defaultOption = document.createElement('option');
                defaultOption.value = '';
                defaultOption.textContent = '-- Select a category --';
                categorySelect.appendChild(defaultOption);
                
                // Add each category as an option
                data.categories.forEach(category => {
                    const option = document.createElement('option');
                    option.value = category.name;
                    option.textContent = category.name;
                    
                    // Add data attributes for additional category info
                    option.dataset.description = category.description || '';
                    option.dataset.icon = category.icon || '';
                    option.dataset.color = category.color || '';
                    
                    categorySelect.appendChild(option);
                });
                
                // If there was a previously selected category, try to reselect it
                const previousValue = categorySelect.dataset.previousValue;
                if (previousValue) {
                    // Look for the option with this value
                    const option = Array.from(categorySelect.options).find(opt => opt.value === previousValue);
                    if (option) {
                        option.selected = true;
                    }
                    // Clear the previous value since we've handled it
                    delete categorySelect.dataset.previousValue;
                }
            })
            .catch(error => {
                console.error('Error fetching categories:', error);
                categorySelect.innerHTML = '<option value="">Error loading categories</option>';
            });
    }
    
    // Create a modal for creating new categories
    const createCategoryButton = document.getElementById('create-category-btn');
    if (createCategoryButton) {
        createCategoryButton.addEventListener('click', function() {
            // Get the current object type
            const objectType = objectTypeSelect.value;
            if (!objectType) {
                alert('Please select an object type first');
                return;
            }
            
            // Show the modal for creating a new category
            const modal = document.getElementById('createCategoryModal');
            if (modal) {
                // Set the object type in the modal form
                const objectTypeInput = modal.querySelector('#category-object-type');
                if (objectTypeInput) {
                    objectTypeInput.value = objectType;
                }
                
                // Show the modal
                const modalInstance = new bootstrap.Modal(modal);
                modalInstance.show();
            } else {
                alert('Category creation modal not found');
            }
        });
    }
    
    // Handle category creation form submission
    const categoryForm = document.getElementById('category-form');
    if (categoryForm) {
        categoryForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Get form data
            const formData = new FormData(categoryForm);
            const categoryData = {
                name: formData.get('category-name'),
                object_type: formData.get('category-object-type'),
                description: formData.get('category-description'),
                icon: formData.get('category-icon'),
                color: formData.get('category-color')
            };
            
            // Send the data to the API
            fetch('/api/categories', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(categoryData),
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    // Close the modal
                    const modal = document.getElementById('createCategoryModal');
                    const modalInstance = bootstrap.Modal.getInstance(modal);
                    if (modalInstance) {
                        modalInstance.hide();
                    }
                    
                    // Reset the form
                    categoryForm.reset();
                    
                    // Reload categories
                    loadCategoriesForType(objectTypeSelect.value);
                    
                    // Show success message
                    alert('Category created successfully!');
                } else {
                    alert('Error creating category: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(error => {
                console.error('Error creating category:', error);
                alert('Error creating category: ' + error.message);
            });
        });
    }
    
    // Handle category suggestion button
    const suggestCategoryButton = document.getElementById('suggest-category-btn');
    if (suggestCategoryButton) {
        suggestCategoryButton.addEventListener('click', function() {
            // Check if we have an object ID (for editing) or need to use form data (for new objects)
            const objectId = this.dataset.objectId;
            
            if (objectId) {
                // For existing objects, use the API to suggest a category
                suggestCategoryButton.disabled = true;
                suggestCategoryButton.textContent = 'Analyzing...';
                
                fetch(`/api/objects/${objectId}/suggest-category`, {
                    method: 'POST'
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.success && data.categories && data.categories.length > 0) {
                        // Clear current selections
                        Array.from(categorySelect.options).forEach(opt => opt.selected = false);
                        
                        // Set the suggested categories in the dropdown
                        data.categories.forEach(categoryName => {
                            const option = Array.from(categorySelect.options).find(opt => opt.value === categoryName);
                            if (option) {
                                option.selected = true;
                            } else {
                                // If a category doesn't exist yet, remember it for after reload
                                if (!categorySelect.dataset.suggestedCategories) {
                                    categorySelect.dataset.suggestedCategories = JSON.stringify([categoryName]);
                                } else {
                                    const suggested = JSON.parse(categorySelect.dataset.suggestedCategories);
                                    suggested.push(categoryName);
                                    categorySelect.dataset.suggestedCategories = JSON.stringify(suggested);
                                }
                            }
                        });
                        
                        // If we need to load new categories, do it
                        if (categorySelect.dataset.suggestedCategories) {
                            loadCategoriesForType(objectTypeSelect.value);
                        }
                        
                        // Update the visual preview
                        updateCategoryPreview();
                    } else {
                        alert('Could not suggest categories: ' + (data.message || 'No suitable categories found'));
                    }
                })
                .catch(error => {
                    console.error('Error suggesting category:', error);
                    alert('Error suggesting category: ' + error.message);
                })
                .finally(() => {
                    suggestCategoryButton.disabled = false;
                    suggestCategoryButton.textContent = 'Suggest Category';
                });
            } else {
                // For new objects, we can only suggest based on the current form data
                alert('Category suggestion for new objects is not yet implemented. Please save the object first, then use the suggestion feature.');
            }
        });
    }
});