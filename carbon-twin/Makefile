.PHONY: install run validate demo test lint clean

install:        ## install dependencies
	pip install -r requirements.txt

run:            ## launch the dashboard
	streamlit run src/dashboard.py

validate:       ## prove the method recovers planted ground truth
	python -m scripts.validate

demo:           ## render the static demo PNGs into assets/
	python -m scripts.render

test:           ## run the test suite
	python -m pytest -q

clean:
	rm -rf __pycache__ */__pycache__ .pytest_cache data/validation_results.csv
