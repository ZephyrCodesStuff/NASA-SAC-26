MIKTEX_BIN := /Applications/MiKTeX Console.app/Contents/bin
PDFLATEX   := "$(MIKTEX_BIN)/miktex-pdftex" -undump=pdflatex -interaction=nonstopmode -halt-on-error
BIBTEX     := "$(MIKTEX_BIN)/miktex-bibtex"

.PHONY: all pdf clean

all: pdf

pdf: main.pdf

main.pdf: main.tex references.bib $(wildcard sections/*.tex)
	$(PDFLATEX) main.tex
	$(BIBTEX) main
	$(PDFLATEX) main.tex
	$(PDFLATEX) main.tex

clean:
	rm -f main.aux main.bbl main.blg main.log main.out main.toc main.pdf
