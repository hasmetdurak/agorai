const App = () => {
    const [query, setQuery] = React.useState('');
    const [responses, setResponses] = React.useState([]);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState(null);
    const [quotaExceeded, setQuotaExceeded] = React.useState(false);
    const [copiedStates, setCopiedStates] = React.useState({});

    // API_URL'i Render backend URL'niz ile değiştirin
    const API_URL = 'https://sizin-render-backend-urlniz.onrender.com/query'; // ÖNEMLİ: Burayı güncelleyin!

    const aiModels = [
        { id: 'chatgpt', name: 'ChatGPT' },
        { id: 'grok', name: 'Grok' },
        { id: 'gemini', name: 'Gemini' },
        { id: 'deepseek', name: 'DeepSeek' }
    ];

    const handleQueryChange = (event) => {
        setQuery(event.target.value);
    };

    const handleSubmit = async () => {
        if (!query.trim()) {
            setError('Lütfen bir soru girin.');
            return;
        }
        setLoading(true);
        setError(null);
        setResponses([]);
        setCopiedStates({});

        try {
            const response = await fetch(API_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ query: query }),
            });

            if (response.status === 429) {
                setQuotaExceeded(true);
                setLoading(false);
                return;
            }

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Bilinmeyen bir sunucu hatası oluştu.' }));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            setResponses(data.responses || []); // Gelen yanıtları işle

        } catch (err) {
            console.error('API isteği başarısız:', err);
            setError(err.message || 'Sonuçlar getirilirken bir hata oluştu.');
        }
        setLoading(false);
    };

    const handleCopy = (text, modelId) => {
        navigator.clipboard.writeText(text)
            .then(() => {
                setCopiedStates(prev => ({ ...prev, [modelId]: true }));
                setTimeout(() => setCopiedStates(prev => ({ ...prev, [modelId]: false })), 2000);
            })
            .catch(err => console.error('Kopyalama başarısız:', err));
    };

    return (
        React.createElement('div', { className: 'container mx-auto p-4' },
            React.createElement('div', { className: 'ad-space mb-6 p-4 bg-gray-100 rounded text-center text-gray-600' }, 'Reklam Alanı'),
            
            React.createElement('h1', { className: 'text-4xl font-bold text-center mb-8 text-blue-600' }, 'AgorAi'),

            React.createElement('div', { className: 'query-bar-container mx-auto flex gap-2 mb-8 max-w-2xl' },
                React.createElement('input', {
                    type: 'text',
                    className: 'query-input flex-grow p-3 border border-gray-300 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                    placeholder: 'AI modellerine ne sormak istersiniz?',
                    value: query,
                    onChange: handleQueryChange,
                    disabled: loading || quotaExceeded
                }),
                React.createElement('button', {
                    className: 'query-button bg-blue-500 hover:bg-blue-700 text-white font-bold py-3 px-6 rounded-lg shadow-md disabled:bg-gray-400',
                    onClick: handleSubmit,
                    disabled: loading || quotaExceeded
                }, loading ? 'Yükleniyor...' : 'Gönder')
            ),

            error && React.createElement('div', { className: 'error-message p-4 mb-6 bg-red-100 border border-red-400 text-red-700 rounded-lg text-center' }, error),

            quotaExceeded && React.createElement('div', { className: 'modal' },
                React.createElement('div', { className: 'modal-content bg-white p-8 rounded-lg shadow-xl' },
                    React.createElement('p', {className: 'text-xl mb-6'}, 'Günlük sorgu limitinizi aştınız. Lütfen yarın tekrar deneyin.'),
                    React.createElement('button', {
                        className: 'bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded',
                        onClick: () => setQuotaExceeded(false) // Modalı kapatmak için basit bir yol, idealde sayfa yenilenmeli veya durum sıfırlanmalı
                    }, 'Anladım')
                )
            ),
            
            loading && React.createElement('div', { className: 'loading-spinner text-center py-10' }, 
                React.createElement('div', {className: 'animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto'}, null),
                React.createElement('p', {className: 'mt-4 text-lg'}, 'Yanıtlar yükleniyor...')
            ),

            !loading && responses.length > 0 && React.createElement('div', { className: 'response-grid grid grid-cols-1 md:grid-cols-2 gap-6' },
                responses.map(item => {
                    const model = aiModels.find(m => m.id === item.model) || { name: item.model };
                    return React.createElement('div', { key: item.model, className: 'response-card bg-white p-6 rounded-lg shadow-lg flex flex-col' },
                        React.createElement('h3', { className: 'text-xl font-semibold mb-3 text-blue-600' }, model.name),
                        React.createElement('div', { className: 'response-content flex-grow bg-gray-50 p-3 rounded border overflow-y-auto max-h-60 mb-4' }, 
                            item.error ? `Hata: ${item.error}` : (item.response || 'Yanıt yok')
                        ),
                        !item.error && item.response && React.createElement('button', {
                            className: `copy-button w-full py-2 px-4 rounded text-white font-semibold ${copiedStates[item.model] ? 'bg-green-600' : 'bg-green-500 hover:bg-green-700'} disabled:bg-gray-300`,
                            onClick: () => handleCopy(item.response, item.model),
                            disabled: !item.response
                        }, copiedStates[item.model] ? 'Kopyalandı!' : 'Yanıtı Kopyala')
                    );
                })
            )
        )
    );
};

ReactDOM.render(React.createElement(App), document.getElementById('root'));