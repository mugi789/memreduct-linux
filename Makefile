.PHONY: deb run lint clean

deb:
	bash packaging/build-deb.sh

run:
	python3 src/memreduct.py

lint:
	python3 -m py_compile src/memreduct.py
	bash -n packaging/build-deb.sh
	rm -rf src/__pycache__

clean:
	rm -rf build dist src/__pycache__
