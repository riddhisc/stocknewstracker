class HistoryManager {
    constructor() {
        this.historyContainer = document.getElementById('history-container');
        this.historyList = document.getElementById('history-list');
        this.clearHistoryBtn = document.getElementById('clear-history');
        this.setupEventListeners();
        this.loadHistory();
    }

    setupEventListeners() {
        this.clearHistoryBtn.addEventListener('click', () => this.clearHistory());
    }

    async loadHistory() {
        try {
            const response = await fetch('/api/history');
            if (!response.ok) {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            const history = await response.json();
            this.displayHistory(history);
        } catch (error) {
            console.error('Error loading history:', error);
            // Create empty history if API fails
            this.displayHistory([]);
        }
    }

    async clearHistory() {
        try {
            const response = await fetch('/api/history', { method: 'DELETE' });
            if (response.ok) {
                this.historyList.innerHTML = '';
                this.historyList.innerHTML = '<p class="no-history">History cleared.</p>';
            } else {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
        } catch (error) {
            console.error('Error clearing history:', error);
            // Show error message
            this.historyList.innerHTML = '<p class="error">Failed to clear history. Please try again.</p>';
        }
    }

    displayHistory(history) {
        this.historyList.innerHTML = '';
        if (!history || history.length === 0) {
            this.historyList.innerHTML = '<p class="no-history">No search history yet. Search for a stock to get started.</p>';
            return;
        }
        
        history.reverse().forEach(item => {
            const historyItem = document.createElement('div');
            historyItem.className = 'history-item';
            
            let date;
            try {
                date = new Date(item.timestamp);
            } catch (e) {
                date = new Date();
            }
            const formattedDate = date.toLocaleString();
            
            historyItem.innerHTML = `
                <div class="history-content">
                    <span class="stock-symbol">${item.stock}</span>
                    <span class="search-date">${formattedDate}</span>
                    <span class="result-count">${item.count !== undefined ? `${item.count} results` : ''}</span>
                </div>
                <button class="search-again-btn" data-stock="${item.stock}">Search Again</button>
            `;
            
            const searchAgainBtn = historyItem.querySelector('.search-again-btn');
            searchAgainBtn.addEventListener('click', () => {
                document.getElementById('stock-input').value = item.stock;
                document.getElementById('search-btn').click();
                
                // Switch to news tab
                document.querySelector('.tab-btn[data-tab="news"]').click();
            });
            
            this.historyList.appendChild(historyItem);
        });
    }
}

// Initialize history manager when the page loads
document.addEventListener('DOMContentLoaded', () => {
    window.historyManager = new HistoryManager();
}); 