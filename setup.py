from setuptools import setup, find_packages  # type: ignore

setup(
    name='nodetools',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[
        'numpy',
        'pandas',
        'sqlalchemy',
        'cryptography',
        'xrpl-py',
        'requests',
        'toml',
        'nest_asyncio','brotli','sec-cik-mapper','psycopg2-binary','quandl','schedule','openai','lxml',
        'gspread_dataframe','gspread','oauth2client','discord','anthropic',
        'bs4',
        'plotly',
        'matplotlib',
        'PyNaCl',
        'loguru',
        'asyncpg',
        'sqlparse',
        'tqdm',
    ],
    include_package_data=True, 
    package_data={
        'nodetools': [
            'sql/*/*.sql',      # Include all .sql files in sql/ subdirectories
            'sql/*.sql',        # Include .sql files directly in sql/
        ],
    },
    author='Alex Good, Skelectric',
    author_email='alex@agti.net, skelectric@postfiat.org',
    description='Post Fiat NodeTools',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/postfiatorg/nodetools',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.11',
    entry_points={
        'console_scripts': [
            'nodetools=nodetools.cli:main',
        ],
    },
)
