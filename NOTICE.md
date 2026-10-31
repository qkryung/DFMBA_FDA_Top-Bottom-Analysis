# Sources, rights and redistribution

This educational research repository does not grant rights to third-party data, models, or software.

- Federal Reserve and SEC original documents are linked in `data/processed/source_manifest.csv`. Raw downloaded pages and extracted source text are not bundled here.
- The current constituent snapshot is attributed to the [datasets S&P 500 repository](https://github.com/datasets/s-and-p-500-companies). Review its source and usage information when reusing the snapshot.
- LM dictionaries are supplied locally by an authorized user. Dictionary hashes are shared; dictionary files are excluded. See [Loughran–McDonald](https://sraf.nd.edu/loughranmcdonald-master-dictionary/).
- FinBERT model weights are downloaded separately and excluded. See the [model card and license](https://huggingface.co/ProsusAI/finbert).
- Licensed classroom CRSP data and all security-level return records derived from them remain local. Only aggregate research metrics are included.
- `report-app/` contains a generated Data App with its supplied protected runtime and dependency lockfile. React and other packages retain their respective licenses. Application authors should edit only the documented content paths and preserve runtime integrity.

Before redistributing an expanded dataset or changing the use from coursework, check the terms of the relevant original sources. No external provider endorses this research.
