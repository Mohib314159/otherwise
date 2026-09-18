.PHONY: install run serve validate validate-app demo test lint clean

install:        ## install dependencies
	pip install -r requirements.txt

run:            ## launch the old CarbonTwin dashboard
	streamlit run src/dashboard.py

serve:          ## launch the Otherwise web app on http://127.0.0.1:8000
	uvicorn src.app.server:app --reload --port 8000

validate:       ## prove the method recovers planted ground truth
	python -m scripts.validate

validate-app:   ## reproduce the app's validation evidence into showcase/validation.md
	python -m scripts.validate_app

demo:           ## render the static demo PNGs into assets/
	python -m scripts.render

test:           ## run the test suite
	python -m pytest -q

clean:
	rm -rf __pycache__ */__pycache__ .pytest_cache data/validation_results.csv
