// Complete order editing functions from orders.html
// Add these functions to waiter_requests.html before the closing });

// Render menu items in edit modal
function renderMenuForEditing(categories, items, specialItems) {
    const container = document.getElementById('editMenuContainer');
    
    let menuHtml = `
        <div id="regularItemsSection">
            <ul class="nav nav-tabs mb-3" id="editCategoryTabs" role="tablist">
    `;
    
    // Category tabs
    categories.forEach((category, index) => {
        menuHtml += `
            <li class="nav-item" role="presentation">
                <button class="nav-link ${index === 0 ? 'active' : ''}" 
                        id="edit-cat-${category.id}-tab" 
                        data-bs-toggle="tab" 
                        data-bs-target="#edit-cat-${category.id}" 
                        type="button" 
                        role="tab">
                    ${category.name}
                </button>
            </li>
        `;
    });
    
    menuHtml += `
            </ul>
            <div class="tab-content" id="editCategoryTabsContent">
    `;
    
    // Category content
    categories.forEach((category, index) => {
        const categoryItems = items.filter(item => item.category_id === category.id);
        
        menuHtml += `
            <div class="tab-pane fade ${index === 0 ? 'show active' : ''}" 
                 id="edit-cat-${category.id}" 
                 role="tabpanel">
                <div class="row g-2">
        `;
        
        categoryItems.forEach(item => {
            menuHtml += `
                <div class="col-md-3 col-sm-4 col-6">
                    <div class="card menu-item-card" 
                         data-item-id="${item.id}" 
                         data-item-name="${item.name}" 
                         data-item-price="${item.price}"
                         style="cursor: pointer; transition: all 0.3s ease;">
                        <div class="card-body p-2 text-center">
                            <h6 class="card-title mb-1" style="font-size: 0.9rem;">${item.name}</h6>
                            <p class="card-text text-muted mb-0" style="font-size: 0.8rem;">${item.price.toFixed(2)} QAR</p>
                        </div>
                    </div>
                </div>
            `;
        });
        
        menuHtml += `
            </div>
        </div>
    `;
    });
    
    menuHtml += `
            </div>
        </div>
        
        <div id="specialItemsSection">
            <hr class="my-3">
            <h6 class="mb-3"><i class="bi bi-stars text-warning me-2"></i>Special Items (طلبات خاصة)</h6>
            <div class="row g-2">
    `;
    
    // Special items
    specialItems.forEach(item => {
        menuHtml += `
            <div class="col-md-3 col-sm-4 col-6">
                <div class="card menu-item-card special-item" 
                     data-item-id="${item.id}" 
                     data-item-name="${item.name}" 
                     data-item-price="${item.price}"
                     style="cursor: pointer; transition: all 0.3s ease; border-color: #ffc107;">
                    <div class="card-body p-2 text-center">
                        <h6 class="card-title mb-1" style="font-size: 0.9rem;">${item.name}</h6>
                        <p class="card-text text-muted mb-0" style="font-size: 0.8rem;">${item.price.toFixed(2)} QAR</p>
                    </div>
                </div>
            </div>
        `;
    });
    
    menuHtml += `
        </div>
    </div>
`;
    
    container.innerHTML = menuHtml;
    
    // Add click handlers for menu items
    container.addEventListener('click', function(e) {
        const menuItem = e.target.closest('.menu-item-card');
        if (menuItem) {
            addItemToEditOrder(menuItem);
        }
    });
}

// Add item to edit order
function addItemToEditOrder(menuItemElement) {
    const itemId = menuItemElement.dataset.itemId;
    const itemName = menuItemElement.dataset.itemName;
    const itemPrice = parseFloat(menuItemElement.dataset.itemPrice);
    const isSpecialItem = menuItemElement.classList.contains('special-item');
    
    // Handle special items differently
    if (isSpecialItem) {
        addSpecialItemToRegularItem(itemId, itemName, itemPrice);
        return;
    }
    
    // Check if it's a custom price item
    if (itemName.toLowerCase().includes('falafel hab') || itemName.toLowerCase().includes('special order')) {
        showCustomPriceModal(itemId, itemName);
        return;
    }
    
    // Check if regular item already exists in order
    const existingItem = editOrderItems.find(item => 
        item.menu_item_id == itemId && !item.is_deleted
    );
    
    if (existingItem) {
        // Increase quantity
        existingItem.quantity += 1;
        existingItem.total_price = existingItem.quantity * existingItem.unit_price;
        existingItem.is_new = true; // Mark as newly added
        
        // Track this as the last selected regular item
        const existingItemIndex = editOrderItems.indexOf(existingItem);
        lastAddedRegularItemIndex = existingItemIndex;
        selectedEditOrderItemIndex = existingItemIndex;
    } else {
        // Add new regular item
        editOrderItems.push({
            id: Date.now(), // Temporary ID for new items
            menu_item_id: itemId,
            menu_item_name: itemName,
            quantity: 1,
            unit_price: itemPrice,
            total_price: itemPrice,
            special_requests: '',
            is_new: true,
            type: 'regular'
        });
        
        // Track this as the last selected regular item
        lastAddedRegularItemIndex = editOrderItems.length - 1;
        selectedEditOrderItemIndex = editOrderItems.length - 1;
    }
    
    renderEditOrderItems();
    updateEditOrderSummary();
    
    // Visual feedback
    menuItemElement.style.backgroundColor = '#d4edda';
    setTimeout(() => {
        menuItemElement.style.backgroundColor = '';
    }, 300);
}

// Add special item as modifier to regular item
function addSpecialItemToRegularItem(itemId, itemName, itemPrice) {
    // Check if there are any regular items in the order
    const regularItems = editOrderItems.filter(item => !item.is_deleted && item.type !== 'special');
    if (regularItems.length === 0) {
        showNotification('Please add a menu item first before adding special requests.', 'warning');
        return;
    }

    let targetItem = null;
    let targetIndex = -1;

    // Priority 1: If an order item is selected, use that
    if (selectedEditOrderItemIndex !== null && 
        selectedEditOrderItemIndex >= 0 && 
        selectedEditOrderItemIndex < editOrderItems.length &&
        !editOrderItems[selectedEditOrderItemIndex].is_deleted) {
        targetItem = editOrderItems[selectedEditOrderItemIndex];
        targetIndex = selectedEditOrderItemIndex;
    } 
    // Priority 2: Use the last added regular item
    else if (lastAddedRegularItemIndex !== null && 
             lastAddedRegularItemIndex >= 0 && 
             lastAddedRegularItemIndex < editOrderItems.length &&
             !editOrderItems[lastAddedRegularItemIndex].is_deleted) {
        targetItem = editOrderItems[lastAddedRegularItemIndex];
        targetIndex = lastAddedRegularItemIndex;
    } 
    // Priority 3: Find the last added regular item (most recent)
    else {
        for (let i = editOrderItems.length - 1; i >= 0; i--) {
            if (!editOrderItems[i].is_deleted && editOrderItems[i].type !== 'special') {
                targetItem = editOrderItems[i];
                targetIndex = i;
                lastAddedRegularItemIndex = i;
                break;
            }
        }
    }

    if (!targetItem) {
        showNotification('No regular item found to attach special request.', 'warning');
        return;
    }

    // Initialize special_items array if it doesn't exist
    if (!targetItem.special_items) {
        targetItem.special_items = [];
    }
    
    // Check if this special item already exists in the array
    const existingSpecialItem = targetItem.special_items.find(si => si.name === itemName);
    if (existingSpecialItem) {
        existingSpecialItem.quantity += 1;
    } else {
        targetItem.special_items.push({
            name: itemName,
            quantity: 1,
            price: itemPrice
        });
    }

    // Add the special item price to the regular item's total
    targetItem.total_price += itemPrice;

    renderEditOrderItems();
    updateEditOrderSummary();

    // Visual feedback
    showNotification(`Added "${itemName}" to "${targetItem.menu_item_name}"`, 'success');
}

// Show custom price modal
function showCustomPriceModal(itemId, itemName) {
    document.getElementById('customPriceItemName').textContent = itemName;
    document.getElementById('customPriceInput').value = '';
    
    const modal = new bootstrap.Modal(document.getElementById('customPriceEditModal'));
    modal.show();
    
    // Store current item data
    modal._currentItemId = itemId;
    modal._currentItemName = itemName;
}

// Render order items in edit modal
function renderEditOrderItems() {
    const container = document.getElementById('editOrderItemsList');
    let itemsHtml = '';
    
    editOrderItems.forEach((item, index) => {
        const isDeleted = item.is_deleted || false;
        const isNew = item.is_new || false;
        
        const isSelected = selectedEditOrderItemIndex === index;
        const selectableClass = !isDeleted ? 'selectable-cart-item' : '';
        const selectedStyle = isSelected ? 'border: 2px solid #007bff; background-color: #f8f9ff;' : '';
        itemsHtml += `
            <div class="card mb-2 order-item-edit ${isDeleted ? 'deleted-item' : ''} ${isNew ? 'new-item' : ''} ${isSelected ? 'selected-item' : ''} ${selectableClass}" 
                 data-index="${index}" 
                 style="cursor: pointer; ${selectedStyle} ${isDeleted ? '' : 'transition: all 0.2s ease;'}">
                <div class="card-body p-2">
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="flex-grow-1">
                            <h6 class="mb-1 ${isDeleted ? 'text-decoration-line-through text-muted' : ''}">
                                ${item.menu_item_name}
                                ${isNew ? '<span class="badge bg-success ms-1">NEW</span>' : ''}
                                ${isDeleted ? '<span class="badge bg-danger ms-1">DELETED</span>' : ''}
                            </h6>
                            <div class="d-flex align-items-center gap-2">
                                ${!isDeleted ? `
                                    <button class="btn btn-sm btn-outline-secondary decrease-qty" data-index="${index}">-</button>
                                    <span class="quantity-display">${item.quantity}</span>
                                    <button class="btn btn-sm btn-outline-secondary increase-qty" data-index="${index}">+</button>
                                ` : `<span class="text-muted">Qty: ${item.quantity}</span>`}
                                <span class="ms-2 ${isDeleted ? 'text-decoration-line-through text-muted' : ''}">
                                    ${item.unit_price.toFixed(2)} QAR each
                                </span>
                            </div>
                            ${item.special_items && item.special_items.length > 0 ? `
                                <div class="mt-1">
                                    <small class="text-info"><i class="bi bi-plus-circle me-1"></i>Special Items:</small>
                                    <div class="ms-3">
                                        ${item.special_items.map(specialItem => `
                                            <small class="text-muted d-block">
                                                ${specialItem.quantity > 1 ? `${specialItem.quantity}x ` : ''}${specialItem.name}
                                            </small>
                                        `).join('')}
                                    </div>
                                </div>
                            ` : (item.special_requests ? `
                                <div class="mt-1">
                                    <small class="text-success"><i class="bi bi-stars me-1"></i>${item.special_requests}</small>
                                </div>
                            ` : '')}
                            ${!isDeleted ? `
                                <div class="mt-1">
                                    <small class="text-primary fw-bold">${isSelected ? '✓ Selected - Click special item to add' : 'Click here to select for special items'}</small>
                                </div>
                            ` : ''}
                        </div>
                        <div class="text-end">
                            <div class="fw-bold ${isDeleted ? 'text-decoration-line-through text-muted' : ''}">
                                ${item.total_price.toFixed(2)} QAR
                            </div>
                            ${!isDeleted ? `
                                <button class="btn btn-sm btn-outline-danger delete-item" data-index="${index}">
                                    <i class="bi bi-trash"></i>
                                </button>
                            ` : `
                                <button class="btn btn-sm btn-outline-success restore-item" data-index="${index}">
                                    <i class="bi bi-arrow-clockwise"></i>
                                </button>
                            `}
                        </div>
                    </div>
                </div>
            </div>
        `;
    });
    
    if (editOrderItems.length === 0) {
        itemsHtml = '<p class="text-muted text-center">No items in order</p>';
    }
    
    container.innerHTML = itemsHtml;
    document.getElementById('editItemsCount').textContent = `${editOrderItems.filter(item => !item.is_deleted).length} items`;
}

// Update order summary
function updateEditOrderSummary() {
    const activeItems = editOrderItems.filter(item => !item.is_deleted);
    const currentTotal = activeItems.reduce((sum, item) => sum + item.total_price, 0);
    const difference = currentTotal - originalOrderTotal;
    
    document.getElementById('editOriginalTotal').textContent = `${originalOrderTotal.toFixed(2)} QAR`;
    document.getElementById('editCurrentTotal').textContent = `${currentTotal.toFixed(2)} QAR`;
    document.getElementById('editItemsCount').textContent = `${activeItems.length} items`;
    
    const differenceElement = document.getElementById('editTotalDifference');
    if (difference > 0) {
        differenceElement.textContent = `+${difference.toFixed(2)} QAR`;
        differenceElement.className = 'text-success';
    } else if (difference < 0) {
        differenceElement.textContent = `${difference.toFixed(2)} QAR`;
        differenceElement.className = 'text-danger';
    } else {
        differenceElement.textContent = '0.00 QAR';
        differenceElement.className = 'text-muted';
    }
}
