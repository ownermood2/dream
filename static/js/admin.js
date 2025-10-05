document.addEventListener('DOMContentLoaded', function() {
    loadQuestions();

    document.getElementById('questionForm').addEventListener('submit', function(e) {
        e.preventDefault();
        
        const question = document.getElementById('question').value;
        const options = Array.from(document.getElementsByName('option[]'))
            .map(input => input.value);
        const correctAnswer = parseInt(document.querySelector('input[name="correct"]:checked').value);
        
        const form = this;
        
        // Check if in edit mode with stricter validation
        if (form.hasAttribute('data-edit-index')) {
            const editIndex = Number(form.dataset.editIndex);
            if (!Number.isInteger(editIndex) || editIndex < 0) {
                showMessage('❌ Invalid edit index', 'danger');
                return;
            }
            
            // Update existing question
            fetch(`/api/questions/${editIndex}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    question: question,
                    options: options,
                    correct_answer: correctAnswer
                })
            })
            .then(response => response.json())
            .then((data) => {
                if (data.status === 'error') {
                    showMessage('Error: ' + data.message, 'danger');
                } else {
                    loadQuestions();
                    cancelEdit();
                    showMessage('✅ Question updated successfully!', 'success');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showMessage('❌ Error updating question. Please try again.', 'danger');
            });
        } else {
            // Add new question
            fetch('/api/questions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    question: question,
                    options: options,
                    correct_answer: correctAnswer
                })
            })
            .then(response => response.json())
            .then((data) => {
                if (data.errors && data.errors.length > 0) {
                    showMessage('⚠️ ' + data.errors.join(', '), 'warning');
                } else {
                    loadQuestions();
                    document.getElementById('questionForm').reset();
                    showMessage('✅ Question added successfully!', 'success');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showMessage('❌ Error adding question. Please try again.', 'danger');
            });
        }
    });
});

function loadQuestions() {
    fetch('/api/questions')
        .then(response => response.json())
        .then(questions => {
            const questionList = document.getElementById('questionList');
            questionList.innerHTML = '';

            questions.forEach((question, index) => {
                const questionElement = document.createElement('div');
                questionElement.className = 'list-group-item';
                questionElement.innerHTML = `
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="flex-grow-1">
                            <h5 class="mb-2"><strong>Q${index + 1}:</strong> ${question.question}</h5>
                            <ul class="list-unstyled mb-0">
                                ${question.options.map((option, i) => `
                                    <li class="mb-1">
                                        ${i === question.correct_answer ? '✅' : '⚪'} ${option}
                                    </li>
                                `).join('')}
                            </ul>
                        </div>
                        <div class="btn-group-vertical ms-3">
                            <button class="btn btn-primary btn-sm mb-1" onclick="editQuestion(${index})">
                                ✏️ Edit
                            </button>
                            <button class="btn btn-danger btn-sm" onclick="deleteQuestion(${index})">
                                🗑️ Delete
                            </button>
                        </div>
                    </div>
                `;
                questionList.appendChild(questionElement);
            });
        })
        .catch(error => console.error('Error:', error));
}

function editQuestion(index) {
    // Fetch the current questions to get the question to edit
    fetch('/api/questions')
        .then(response => response.json())
        .then(questions => {
            const question = questions[index];
            if (!question) return;
            
            // Populate the form with current values
            document.getElementById('question').value = question.question;
            const optionInputs = document.getElementsByName('option[]');
            question.options.forEach((opt, i) => {
                if (optionInputs[i]) optionInputs[i].value = opt;
            });
            
            // Set correct answer radio button
            const correctRadios = document.getElementsByName('correct');
            correctRadios[question.correct_answer].checked = true;
            
            // Change form behavior to edit mode
            const form = document.getElementById('questionForm');
            const submitBtn = form.querySelector('button[type="submit"]');
            submitBtn.textContent = 'Update Question';
            submitBtn.classList.remove('btn-primary');
            submitBtn.classList.add('btn-warning');
            
            // Store the index for later use
            form.dataset.editIndex = index;
            
            // Add cancel button if not exists
            let cancelBtn = document.getElementById('cancelEditBtn');
            if (!cancelBtn) {
                cancelBtn = document.createElement('button');
                cancelBtn.id = 'cancelEditBtn';
                cancelBtn.type = 'button';
                cancelBtn.className = 'btn btn-secondary ms-2';
                cancelBtn.textContent = 'Cancel';
                cancelBtn.onclick = cancelEdit;
                submitBtn.parentElement.appendChild(cancelBtn);
            }
            
            // Scroll to form
            form.scrollIntoView({ behavior: 'smooth', block: 'start' });
        })
        .catch(error => console.error('Error:', error));
}

function cancelEdit() {
    const form = document.getElementById('questionForm');
    form.reset();
    
    // Properly remove the edit index
    if (form.dataset.editIndex) {
        delete form.dataset.editIndex;
    }
    form.removeAttribute('data-edit-index');
    
    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.textContent = 'Add Question';
    submitBtn.classList.remove('btn-warning');
    submitBtn.classList.add('btn-primary');
    
    const cancelBtn = document.getElementById('cancelEditBtn');
    if (cancelBtn) cancelBtn.remove();
}

function showMessage(message, type) {
    // Create alert element
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show mt-3`;
    alertDiv.role = 'alert';
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    // Insert after form
    const form = document.getElementById('questionForm');
    form.parentElement.parentElement.insertBefore(alertDiv, form.parentElement.nextSibling);
    
    // Auto-dismiss after 5 seconds
    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

function deleteQuestion(index) {
    if (!confirm('Are you sure you want to delete this question?')) return;
    
    fetch(`/api/questions/${index}`, {
        method: 'DELETE'
    })
    .then(response => response.json())
    .then((data) => {
        if (data.status === 'error') {
            showMessage('Error: ' + data.message, 'danger');
        } else {
            loadQuestions();
            showMessage('✅ Question deleted successfully!', 'success');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showMessage('❌ Error deleting question. Please try again.', 'danger');
    });
}
