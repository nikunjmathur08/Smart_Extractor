# Contributing to Smart Extractor

Thank you for your interest in contributing to Smart Extractor! We welcome contributions from the community and are excited to see how you can help make this voice-controlled web scraper even better.

## How to Contribute

### Types of Contributions

We welcome several types of contributions:

- **Bug Reports**: Help us identify and fix issues
- **Feature Requests**: Suggest new functionality or improvements
- **Code Contributions**: Submit pull requests with bug fixes or new features
- **Documentation**: Improve README, add examples, or write tutorials
- **Testing**: Add test cases or improve existing ones
- **UI/UX**: Enhance the terminal interface and user experience

## Getting Started

### Prerequisites

Before contributing, make sure you have:

- **macOS** (required for testing voice functionality)
- **Python 3.8+**
- **Git** installed and configured
- **Ollama** with LLaMA 3.1 8B-instruct-q4_K_M model
- Basic knowledge of Python, web scraping and AI/ML concepts

### Setting Up Your Development Environment

1. **Fork the repository**
   ```bash
   # Click the "Fork" button on GitHub, then clone your fork
   git clone https://github.com/YOUR_USERNAME/Smart_Extractor.git
   cd Smart_Extractor
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On macOS/Linux
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up Ollama**
   ```bash
   ollama pull llama3.1:8b-instruct-q4_K_M
   ```

5. **Test the setup**
   ```bash
   # Test text mode
   python full_extract.py
   
   # Test voice mode (ensure microphone is working)
   > cd trials/
   > python speech.py
   ```

## Development Guidelines

### Code Style

- Follow **PEP 8** Python style guidelines
- Use meaningful variable and function names
- Add docstrings to all functions and classes
- Keep functions focused and modular
- Use type hints where appropriate

```python
def extract_product_data(url: str, max_items: int = 50) -> List[Dict[str, Any]]:
    """
    Extract product data from an e-commerce website.
    
    Args:
        url (str): The website URL to scrape
        max_items (int): Maximum number of items to extract
        
    Returns:
        List[Dict[str, Any]]: List of product dictionaries
    """
    pass
```

### Project Structure

When adding new features, maintain the existing structure:

```
Smart_Extractor/
├── modelFiles/         # AI model-specific files
├── trials/             # Experimental code (not for production)
├── tests/              # Test files (please add tests!)
├── full_extract.py     # Main text-based program
├── full_speech.py      # Main voice-controlled program
└── utils/              # Utility functions (if needed)
```

### Commit Messages

Use clear, descriptive commit messages:

```bash
# Good examples
git commit -m "feat: add support for Best Buy product scraping"
git commit -m "fix: fix voice recognition timeout issue"
git commit -m "feat: improve error handling for blocked websites"

# Avoid
git commit -m "fix bug"
git commit -m "update code"
```

## Reporting Issues

### Before Reporting

1. Check existing [issues](https://github.com/nikunjmathur08/Smart_Extractor/issues)
2. Test with the latest version
3. Try both text and voice modes
4. Test on a clean macOS environment if possible

### Issue Template

When reporting bugs, please include:

```markdown
## Bug Description
A clear description of what the bug is.

## Steps to Reproduce
1. Run `python full_speech.py`
2. Say "scrape laptops from Amazon"
3. See error

## Expected Behavior
What you expected to happen.

## Actual Behavior
What actually happened.

## Environment
- macOS Version: [e.g., macOS 14.1]
- Python Version: [e.g., 3.9.7]
- Ollama Version: [e.g., 0.1.32]
- Smart Extractor Version: [e.g., latest commit hash]

## Additional Context
- Error messages (full traceback)
- Screenshots or terminal output
- Any relevant logs
```

## Feature Requests

We love new ideas! When suggesting features:

1. **Check existing issues** to avoid duplicates
2. **Explain the use case** - why is this feature needed?
3. **Describe the solution** - how should it work?
4. **Consider alternatives** - are there other ways to solve this?

### Priority Areas

We're particularly interested in contributions for:

- **Multi-platform support** (Windows/Linux compatibility)
- **Additional website support** (beyond Amazon/Flipkart/Walmart)
- **Improved AI models** (better intent recognition, query construction)
- **Data export formats** (databases, APIs, more file types)
- **Enhanced anti-detection** (better proxy support, CAPTCHA handling)
- **Testing framework** (unit tests, integration tests)
- **Mobile integration** (iOS shortcuts, Android support)

## Code Contributions

### Pull Request Process

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/issue-description
   ```

2. **Make your changes**
   - Write clean, documented code
   - Add tests if applicable
   - Update documentation if needed

3. **Test thoroughly**
   ```bash
   # Test both modes
   python full_extract.py
   python full_speech.py
   
   # Test edge cases
   # Test with different websites
   # Test error conditions
   ```

4. **Commit and push**
   ```bash
   git add .
   git commit -m "Add feature: description of your changes"
   git push origin feature/your-feature-name
   ```

5. **Create a Pull Request**
   - Use the PR template
   - Link related issues
   - Add screenshots/demos if relevant

### Pull Request Template

```markdown
## Description
Brief description of changes made.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Code refactoring

## Testing
- [ ] Tested with `full_extract.py`
- [ ] Tested with `full_speech.py`
- [ ] Tested with multiple websites
- [ ] Tested error scenarios
- [ ] Added/updated tests

## Checklist
- [ ] Code follows project style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No breaking changes (or clearly documented)

## Screenshots/Demos
If applicable, add screenshots or terminal recordings.
```

## Testing

### Running Tests

```bash
# Run all tests (when available)
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_voice_recognition.py

# Run with coverage
python -m pytest --cov=smart_extractor tests/
```

### Adding Tests

When adding new features, please include tests:

```python
# tests/test_scraping.py
import pytest
from smart_extractor.scraping import extract_product_data

def test_amazon_scraping():
    """Test Amazon product data extraction."""
    url = "https://amazon.in/s?k=laptop"
    data = extract_product_data(url, max_items=5)
    
    assert len(data) > 0
    assert all('name' in item for item in data)
    assert all('price' in item for item in data)
```

## Documentation

### Improving Documentation

- **README updates**: Keep installation and usage instructions current
- **Code comments**: Explain complex algorithms or AI model interactions
- **Examples**: Add more usage examples and edge cases
- **API documentation**: Document functions and classes

### Writing Style

- Use clear, concise language
- Include code examples
- Add screenshots or terminal output where helpful
- Consider different skill levels

## Specific Contribution Areas

### AI Model Improvements

If you're working on AI models:

- **Prompt engineering**: Improve prompts in `prompts/` directory
- **Model fine-tuning**: Enhance specialized models in `modelFiles/`
- **Intent recognition**: Better understanding of user requests
- **Query construction**: More accurate web scraping queries

### Web Scraping Enhancements

- **New websites**: Add support for more e-commerce sites
- **Anti-detection**: Improve methods to avoid blocking
- **Data extraction**: Better parsing of product information
- **Error handling**: More graceful failure recovery

### Voice Interface Improvements

- **Cross-platform**: Make voice work on Windows/Linux
- **Better recognition**: Improve speech-to-text accuracy
- **Voice commands**: Add more natural language patterns
- **Audio feedback**: Better text-to-speech responses

## Important Notes

### Legal and Ethical Considerations

- **Respect robots.txt**: Always check and follow website policies
- **Rate limiting**: Don't overwhelm servers
- **Copyright**: Ensure scraped data usage complies with laws
- **Privacy**: Handle user data responsibly

### macOS Dependency

Currently, Smart Extractor requires macOS due to the `say` command. If you're interested in multi-platform support:

- Research TTS alternatives for Windows/Linux
- Consider using cross-platform libraries
- Maintain backward compatibility with macOS

## Community

### Getting Help

- **GitHub Issues**: For bugs and feature requests
- **GitHub Discussions**: For general questions and ideas
- **Code Reviews**: Learn from feedback on your PRs

### Recognition

Contributors will be recognized in:
- **README.md**: Contributors section
- **Release notes**: Major contribution mentions
- **GitHub**: Contributor badges and statistics

## Contact

For questions about contributing:

- **GitHub Issues**: Public discussions
- **Email**: nikunjmathur0810@gmail.com
- **GitHub Discussions**: Community forum

## License

This project is currently under review for licensing terms. All contributions will be subject to the final license as determined by the project maintainer.

For now, assume **personal and educational use only**, with no commercial redistribution or derivative works unless explicitly permitted.

See the [LICENSE](LICENSE) file for the most up-to-date licensing information. If you have questions, please reach out via Issues or email.

---

**Thank you for contributing to Smart Extractor! Your help makes this project better for everyone.**

## Quick Start Checklist

Ready to contribute? Here's your quick checklist:

- [ ] Fork the repository
- [ ] Set up development environment
- [ ] Create feature branch
- [ ] Make changes with tests
- [ ] Update documentation
- [ ] Submit pull request
- [ ] Respond to code review feedback

**Happy coding!**