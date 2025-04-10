document.addEventListener('DOMContentLoaded', () => {
    const stockInput = document.getElementById('stock-input');
    const searchBtn = document.getElementById('search-btn');
    const newsContainer = document.getElementById('news-container');
    const loading = document.getElementById('loading');
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    // Tab switching
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.getAttribute('data-tab');
            
            // Update active tab button
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Update active tab pane
            tabPanes.forEach(pane => {
                pane.classList.remove('active');
                if (pane.id === `${tabName}-tab`) {
                    pane.classList.add('active');
                }
            });
            
            // If switching to history tab, refresh the history
            if (tabName === 'history' && window.historyManager) {
                window.historyManager.loadHistory();
            }
        });
    });

    // Search functionality
    async function searchStock() {
        const stock = stockInput.value.trim();
        if (!stock) return;

        loading.classList.remove('hidden');
        newsContainer.innerHTML = '';

        try {
            const response = await fetch('/search', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `stock=${encodeURIComponent(stock)}`
            });

            if (!response.ok) {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }

            const data = await response.json();
            console.log("API Response:", data); // Debug log to see what we're getting
            
            // More robust handling of news data
            let newsData = [];
            if (data && typeof data === 'object') {
                if (Array.isArray(data)) {
                    // If the response itself is an array
                    newsData = data;
                } else if (data.news && Array.isArray(data.news)) {
                    // If the response has a news property that's an array
                    newsData = data.news;
                } else if (data.news) {
                    // If news exists but isn't an array, try to convert it
                    try {
                        newsData = [].concat(data.news);
                    } catch (e) {
                        console.error("Couldn't convert news to array:", e);
                        newsData = [];
                    }
                }
            }
            
            if (newsData.length > 0) {
                newsData.forEach(article => {
                    if (!article) return;
                    
                    const newsCard = document.createElement('div');
                    newsCard.className = 'news-card';
                    
                    // Get publication date
                    let pubDate;
                    try {
                        pubDate = new Date(article.published_at).toLocaleString();
                    } catch (e) {
                        pubDate = 'Unknown date';
                    }
                    
                    newsCard.innerHTML = `
                        <h3>${article.title || 'No Title'}</h3>
                        <p>${article.description || 'No description available'}</p>
                        <p><strong>Source:</strong> ${article.source || 'Unknown'}</p>
                        <p><strong>Published:</strong> ${pubDate}</p>
                        <a href="${article.url}" target="_blank">Read more</a>
                        ${article.type === 'sample' ? '<span class="sample-tag">Sample News</span>' : ''}
                    `;
                    newsContainer.appendChild(newsCard);
                });
                
                // Update the history tab data if needed
                if (window.historyManager) {
                    window.historyManager.loadHistory();
                }
            } else {
                newsContainer.innerHTML = '<p class="no-results">No news found for this stock. Try another search term.</p>';
            }
        } catch (error) {
            console.error('Error fetching news:', error);
            newsContainer.innerHTML = `<p class="error">Error fetching news: ${error.message}. Please try again.</p>`;
        } finally {
            loading.classList.add('hidden');
        }
    }

    // Event listeners
    searchBtn.addEventListener('click', searchStock);
    stockInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            searchStock();
        }
    });
}); 