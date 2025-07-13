# Smart Extractor

A dynamic terminal-based web scraper with full voice control capabilities. Literally use just your voice to scrape the internet! Smart Extractor combines the power of AI-driven intent recognition with advanced web scraping techniques to deliver a seamless, hands-free data extraction experience.

## Features

### Voice-Powered Interface
- **Complete Voice Control**: Interact with the scraper using natural speech
- **Real-time Speech Processing**: Instant voice recognition and response
- **Hands-free Operation**: Perfect for accessibility and multitasking

### AI-Powered Intelligence
- **Intent Recognition**: Understands what you want to scrape from natural language
- **Smart Query Generation**: Creates structured queries from conversational input
- **Follow-up Questions**: Asks clarifying questions to improve search accuracy
- **Query Refinement**: Continuously improves search parameters based on your responses

### Advanced Scraping Capabilities
- **Anti-Detection Measures**: Multiple strategies to avoid getting blocked
- **Dynamic Content Handling**: Handles JavaScript-heavy sites
- **Robust Error Handling**: Graceful failure recovery
- **Rate Limiting**: Respectful scraping practices
- **Waits for Images**: Waits for images to load on a website and then begin scraping

### Supported Websites

Smart Extractor works exceptionally well with major e-commerce platforms:

- **Amazon** - Products, prices, reviews, specifications
- **Flipkart** - Indian e-commerce marketplace
- **Walmart** - Product listings and pricing
- **Custom Websites** - Any site you specify (with varying success rates)

The system is optimized for e-commerce scraping but can adapt to other content types through its intelligent query construction.

### Specialized AI Models
- **Intent Classifier**: Identifies user's scraping objectives
- **Query Constructor**: Builds structured search parameters
- **Question Generator**: Creates relevant follow-up questions
- **Response Analyzer**: Processes user feedback for query improvement

Each model uses carefully crafted prompts stored in the `modelFiles/` directory, giving the LLM clear guidance on how to handle specific tasks with maximum precision and effectiveness.

## Getting Started

### Prerequisites

- **macOS** (required for Siri's Samantha voice integration)
- Python 3.8+
- Ollama with LLaMA 3.1 8B model
- Microphone for voice input
- Internet connection

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/nikunjmathur08/Smart_Extractor.git
   cd Smart_Extractor
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   
   The main dependencies include:
   - `crawl4ai` - Advanced web scraping framework
   - `speech_recognition` - Voice input processing
   - `pandas` - Data manipulation and CSV export
   - `asyncio` - Asynchronous operations
   - Standard libraries: `re`, `subprocess`, `urllib`

3. **Set up Ollama**
   ```bash
   # Install Ollama (if not already installed)
   curl -fsSL https://ollama.ai/install.sh | sh
   
   # Pull the LLaMA 3.1 8B model
   ollama pull llama3.1:8b-instruct-q4_K_M
   ```
5. **Configure respective models**
    ```bash
    # Install QueryLlama model
    > cd modelFiles
    > ollama create query-llama -f QueryLlama.modelfile

    # Install FollowUps model
    > cd modelFiles
    > ollama create follow-ups -f AskFollowUps.modelfile

    # Install RefineQuery model
    > cd modelFiles
    > ollama create refine-query -f RefineQuery.modelfile
    ```

4. **Configure audio settings**
   - Ensure your microphone is working and properly configured
   - The system uses macOS's built-in `say` command with Samantha voice
   - Test voice input: "Hey Siri" or any voice command should work
   - Adjust microphone sensitivity in System Preferences if needed

### Quick Start

**Text-based scraping:**
```bash
python full_extract.py
```

**Voice-controlled scraping:**
```bash
python full_speech.py
```

Then simply speak your scraping request:
- "I want to buy a MacBook from Amazon"
- "I am looking for healthy snacks on Walmart"

## How It Works

### Performance

#### Speed Optimizations
- **End-to-end processing**: ~1 minute from voice input to saved data
- **Optimized AI inference**: Efficient prompt engineering reduces processing time
- **Concurrent scraping**: Asynchronous operations for faster data extraction
- **Smart caching**: Reduces redundant API calls

#### Typical Workflow Timeline
1. **Voice Recognition**: 2-3 seconds
2. **AI Processing**: 10-15 seconds (intent → query → refinement)
3. **Web Scraping**: 30-40 seconds (depending on data volume)
4. **Data Processing & Export**: 5-10 seconds

### 1. Voice Input Processing
The system captures your voice input and converts it to text using advanced speech recognition.

### 2. Intent Analysis
The specialized intent recognition model analyzes your request to understand:
- What type of data you want
- Which websites to target
- How to structure the extraction

### 3. Interactive Refinement
Smart Extractor asks follow-up questions to clarify:
- Specific data fields needed
- Date ranges or filters
- Output format preferences

### 4. Query Construction
Based on your responses, it builds a structured query optimized for web scraping.

### 5. Intelligent Scraping
Using Crawl4AI, it executes the scraping with:
- Rotating user agents
- Proxy support
- JavaScript rendering
- Content validation

## Technical Architecture

### Project Structure

```
Smart_Extractor/
├── modelFiles/         # Specialized AI models for different tasks
├── trials/             # Experimental implementations
├── full_extract.py     # Main text-based scraping program
├── full_speech.py      # Main voice-controlled program
├── chairs.xlsx         # Sample output file
├── requirements.txt    # Python dependencies
├── README.md           # This file
└── .gitignore          # Git ignore rules
```

### Core Components

```
Smart Extractor
├── Voice Interface (speech_recognition + Siri's Samantha)
│   ├── Speech Recognition
│   ├── Text-to-Speech (macOS native)
│   └── Audio Processing
├── AI Models (Ollama + LLaMA 3.1)
│   ├── Intent Classifier (modelFiles/)
│   ├── Query Constructor
│   ├── Question Generator
│   └── Response Analyzer
├── Web Scraping Engine
│   ├── Crawl4AI Integration
│   ├── Anti-Detection
│   └── Content Extraction
└── Output Processing
    ├── Data Validation
    ├── Pandas DataFrame
    └── CSV/XLSX Export
```

### Key Technologies

- **Ollama**: Local AI model inference
- **LLaMA 3.1 8B-instruct-q4_K_M**: Language understanding and generation
- **Crawl4AI**: Advanced web scraping framework
- **SpeechRecognition**: Voice input processing
- **macOS `say` command**: Native text-to-speech with Samantha voice
- **Pandas**: Data manipulation and analysis
- **AsyncIO**: Asynchronous programming support

## Usage Examples

### Basic Product Scraping
```
🎤 You: "I want to scrape product information from e-commerce sites"
🤖 Bot: "What specific products are you looking for?"
🎤 You: "Laptops under $1000"
🤖 Bot: "Which e-commerce sites should I target?"
🎤 You: "Amazon and Walmart"
🤖 Bot: "What information do you need? Price, specs, reviews?"
🎤 You: "Price, model name, and customer ratings"
🤖 Bot: "Starting extraction..."
```

## Advanced Features

### Custom Intent Models
The specialized models in `modelFiles/` use intuitive prompts that give the LLM clear guidance:

```python
def ask_ollama (model: str, prompt: str, stream=False) -> str:
  url = "http://localhost:11434/api/generate"
  headers = {"Content-Type": "application/json"}
  payload = {
    "model": model,
    "prompt": prompt,
    "stream": stream
  }

  response = requests.post(url, headers=headers, json=payload, timeout=60)
  response.raise_for_status()

  if stream:
    output = ""
    for line in response.iter_lines():
      if line:
        chunk = json.loads(line.decode("utf-8"))
        output += chunk.get("response", "")
    return output
  else:
    return response.json().get("response", "")
```

### Dual Mode Operation
- **Text Mode**: `full_extract.py` - Traditional keyboard input
- **Voice Mode**: `full_speech.py` - Complete voice control with Siri integration

### Robust Error Handling
- **Voice Recognition Failures**: Automatically displays error message and suggests using text mode
- **Website Blocking**: Graceful exit with informative error messages
- **Network Issues**: Retry mechanisms with exponential backoff

### Fallback Mechanisms
- **Voice → Text**: If voice recognition fails, users can switch to `full_extract.py`
- **Primary → Secondary Sites**: If main target is blocked, tries alternative sources
- **Complex → Simple Queries**: Reduces query complexity if initial attempts fail

### Experimental Features
Check the `trials/` directory for:
- Alternative implementation approaches
- Performance optimizations
- New scraping techniques
- Enhanced AI model configurations

## Anti-Detection Features

- **Dynamic Headers**: Rotates user agents and headers
- **Request Timing**: Delays between requests
- **Session Management**: Maintains persistent sessions
- **Proxy Support**: Routes through proxy servers
- **JavaScript Rendering**: Handles dynamic content

## Sample Output

### E-commerce Product Data (CSV Format)

```csv
Product Name,Price,Rating,URL
"Apple 2024 MacBook Pro Laptop with M4 chip with 10‑core CPU and 10‑core GPU: Built for Apple Intelligence, 35.97 cm (14.2″) Liquid Retina XDR Display, 16GB Unified Memory, 512GB SSD Storage; Silver",162990,,"https://www.amazon.in/Apple-2024-MacBook-Laptop-10%E2%80%91core/dp/B0DLHNB9MY/..."
"Lenovo Smartchoice Ideapad Slim 3 13Th Gen Intel Core I7-13620H 15.3 Inch(38.8Cm) WUXGA IPS Laptop(16GB RAM/512GB SSD/Windows 11/Office Home 2024/Backlit Keyboard/1Yr ADP Free/Grey/1.6Kg)",65990,,"https://www.amazon.in/sspa/click?ie=UTF8&spc=MTo0MzMzMDA2NTk3ODgzNTgw..."
"Lenovo IdeaPad Pro 5 Intel Core Ultra 9 185H Built-in AI 14"" (35.5cm) 2.8K OLED 400Nits 120Hz Laptop (32GB RAM/1TB SSD/Windows 11/Office Home 2024/1Yr ADP Free/Grey/1.46Kg)",110990,,"https://www.amazon.in/sspa/click?ie=UTF8&spc=MTo0MzMzMDA2NTk3ODgzNTgw..."
```

### Output Formats

Smart Extractor supports multiple output formats:
- **CSV**: Spreadsheet-friendly format (default)
- **XLSX**: Excel files with formatting
- **JSON**: Structured data for APIs
- **Pandas DataFrame**: For further Python processing

Example files are saved in the project directory (e.g., `chairs.xlsx`).

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

## License

This project is currently under review for licensing terms. All contributions will be subject to the final license as determined by the project maintainer.

For now, assume **personal and educational use only**, with no commercial redistribution or derivative works unless explicitly permitted.

See the [LICENSE](LICENSE) file for the most up-to-date licensing information. If you have questions, please reach out via Issues or email.

## Ethical Usage

Please use Smart Extractor responsibly:
- Respect robots.txt files
- Don't overload servers
- Follow website terms of service
- Consider rate limiting
- Respect copyright and data privacy

## Troubleshooting

### Common Issues

**Voice Recognition Not Working**
- Check microphone permissions in System Preferences > Security & Privacy
- Verify microphone is working: try "Hey Siri" or voice memos
- If voice continues to fail, switch to text mode: `python full_extract.py`
- Adjust microphone sensitivity in System Preferences > Sound

**Scraping Getting Blocked**
- System will gracefully exit with error message
- Try different websites or reduce scraping frequency
- Consider using proxy settings (if implemented)
- Check internet connection and target website status

**AI Model Errors**
- Ensure Ollama is running: `ollama serve`
- Verify LLaMA 3.1 model is installed: `ollama list`
- Check system resources (RAM usage)
- Restart Ollama service if needed

**macOS Compatibility**
- This tool requires macOS due to the `say -v Samantha` command
- For other operating systems, consider modifying the TTS implementation
- Text mode (`full_extract.py`) may work on other platforms with minor modifications

### Getting Help

- [Documentation](docs/)
- [Issue Tracker](https://github.com/nikunjmathur08/Smart_Extractor/issues)
- [Discussions](https://github.com/nikunjmathur08/Smart_Extractor/discussions)
- [Contact](mailto:nikunjmathur0810@gmail.com)

## Acknowledgments

- Ollama team for the excellent AI inference platform
- Crawl4AI developers for the robust scraping framework
- LLaMA team for the powerful language model
- Open source community for inspiration and contributions

---

**Star this repository if you find it helpful!**

Built with ❤️ by [Nikunj Mathur](https://github.com/nikunjmathur08)
