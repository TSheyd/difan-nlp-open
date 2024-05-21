"""
Complete ML Pipeline for stock news sentiment analysis, built with Dagster
"""

import time
from datetime import date, timedelta
import requests

import pandas as pd
import numpy as np
from mysql.connector import connect
from fuzzywuzzy import fuzz
from fuzzywuzzy import process

from transformers import AutoTokenizer, AutoModelForSequenceClassification, AutoModelForCausalLM
from dagster import asset, AssetIn, get_dagster_logger
from span_marker import SpanMarkerModel


from config import *


model_name = "mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis"
ner_model_name = "Universal-NER/UniNER-7B-all"


logger = get_dagster_logger()


@asset(group_name='parsing_new_data')
def tickers_list() -> list:
    """
    Get the list of tracked tickers
    """
    with connect(**difan) as con:
        cur = con.cursor()

        cur.execute("SELECT ticker, company "
                    "FROM tickers.List ")
                    # "WHERE delistedDate IS NULL AND (primaryTickerId=id OR primaryTickerId IS NULL) AND trackNews=1")
        tickers = pd.DataFrame(cur.fetchall(), columns=['ticker', 'company']).set_index('ticker')
    logger.info(f'Got {tickers.shape[0]} from List')
    return tickers


@asset(group_name='model_inference')
def ner_model():
    """
    Load huggingface model for NER
    :return:
    """
    ner_model = AutoModelForCausalLM.from_pretrained(ner_model_name)
    return ner_model


@asset(group_name='model_inference')
def classifier_model():
    """
    Load huggingface model
    :return:
    """
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    return model


@asset(group_name='model_inference')
def model_tokenizer():
    """
    Init tokenizer
    :return:
    """
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    return tokenizer


# alternatively, @asset(ins={"news_df": AssetIn("unprocessed_news_articles")})
@asset(group_name='model_inference')
def run_inference(
        tickers_list,
        unprocessed_news_articles,
        classifier_model,
        ner_model,
        model_tokenizer
) -> pd.DataFrame:
    """
    Process dataframe rows with sentiment analysis model and NER model

    :param unprocessed_news_articles:
    :param classifier_model:
    :param model_tokenizer:
    :return:
    """

    # Функция, чтобы отфильтровать только организации
    def filter_organizations(entities) -> list:
        return [entity for entity in entities if 'ORG' in entity['label']]

    # NER inference
    def filter_organizations(entities):
        return [entity for entity in entities if 'ORG' in entity['label']]

    def find_entity(df: pd.DataFrame) -> pd.DataFrame:
        predict = ner_model.predict(df['text'])
        org_entities = filter_organizations(predict)
        stack = []

        for i in range(len(org_entities)):
            stack.append(org_entities[i]['span'])

        df['entity'] = stack

        # Выполняем fuzzy matching для извлечения потенциальных компаний
        extraction_results = process.extract(str(df['entity']), tickers_list.index.tolist(), limit=5)

        # Фильтруем компании со score >= 87
        matching_companies = [company for company, score in extraction_results if score >= 87]

        if matching_companies:
            # Получаем коды компаний, соответствующие matching_companies
            matching_codes = [
                tickers_list[tickers_list['company'] == company]['ticker'].values[0] for company in matching_companies
            ]

            # codes_str = ", ".join(matching_codes)

            df['tickersMentioned'] = matching_codes  # stored as list

        return df['tickers']

    # Sentiment inference
    def predict_sentiment(df: pd.DataFrame) -> pd.DataFrame:
        inputs = model_tokenizer(df['text'], return_tensors="pt", truncation=True)
        outputs = classifier_model(**inputs)
        df[['neg', 'neu', 'pos']] = outputs.logits.softmax(dim=1)[0].tolist()  # 0 to 1, sum up to 1
        return df

    unprocessed_news_articles = unprocessed_news_articles.apply(predict_sentiment, axis=1)
    unprocessed_news_articles = unprocessed_news_articles.apply(find_entity, axis=1)

    return unprocessed_news_articles


@asset(ins={"data": AssetIn("run_inference")})
def load_data(data) -> None:
    """
    load calculated sentiment in a database
    """

    data = data.reset_index(drop=False, names='id')
    data = list(data[['neg', 'neu', 'pos', 'tickersMentioned', 'id']].itertuples(index=False, name=None))

    with connect(**hse) as con:
        cur = con.cursor()

        cur.executemany("UPDATE news.dataset SET neg=%s, neu=%s, pos=%s, tickersMentioned=%s WHERE id=%s", data)
        con.commit()
        print(f'loaded {cur.rowcount} sentiment datapoints')

    return None


@asset
def unprocessed_news_articles() -> pd.DataFrame:
    """
    Returns all the unprocessed rows from news database
    :return:
    """

    with connect(**hse) as con:
        cur = con.cursor()

        cur.execute("SELECT id, title, content "
                    "FROM news.dataset "
                    "WHERE neg IS NULL ORDER BY date DESC LIMIT 500")
        # all 3 sentiment columns are null by default, (0, 1] if processed and 0 if could not be processed.
        # It is enough to check by just one of the columns

        unprocessed_records = pd.DataFrame(cur.fetchall(), columns=['id', 'title', 'content']).set_index('id')

    unprocessed_records['content'] = unprocessed_records['content'].fillna('')
    unprocessed_records['text'] = unprocessed_records['title'] + ' ' + unprocessed_records['content']
    unprocessed_records['text'] = unprocessed_records['text'].str.strip()
    unprocessed_records[['neg', 'neu', 'pos']] = 0, 0, 0

    logger.info(f'Captured {cur.rowcount} unprocessed records for inference')

    return unprocessed_records


@asset(group_name='parsing_new_data')
def cutoff_date() -> date:
    """
    Get the last date on which there are any records in the database
    """
    with connect(**hse) as con:
        cur = con.cursor()
        cur.execute("SELECT MAX(date) FROM news.dataset")
        max_date = cur.fetchone()[0]
    con.close()
    logger.info(f'Cutoff date for news parsing is: {max_date}')
    return max_date



@asset(group_name='parsing_new_data')
def news_articles_FMP(tickers_list, cutoff_date) -> pd.DataFrame:
    """
    Gets stock news from [FMP API](https://site.financialmodelingprep.com/developer/docs#news)

    :param list tickers_list: список тикеров
    :param datetime.date cutoff_date: start date for parsing
    :return:
    """
    fdf = pd.DataFrame()

    for i in range(50, 90):
        data = requests.get(f"{API_HOST_v3}stock_news?limit=1000&page={i}&apikey={API_KEY}").json()
        df = pd.DataFrame(data)

        if df.empty:
            break

        df['publishedDate'] = pd.to_datetime(df['publishedDate'])
        df['date'] = pd.to_datetime(df['publishedDate']).dt.date

        df = df.rename(columns={'symbol': 'ticker', 'text': 'content', 'site': 'publisher'})
        df = df[['ticker', 'date', 'publisher', 'url', 'title', 'content']]
        df = df.loc[df['ticker'].isin(tickers_list.index)]

        print(f"{i} - {df.shape[0]}")

        if df.empty:
            break

        if df.date.min() < cutoff_date: # or (i > 10 and df.iloc[0]['date'] > date.today() - timedelta(days=7)):
            # Второе условие осталось от заполнения базы и в регулярных процессах возникать не должно:
            #   у этой апишки большие значения page сбрасываются на первую страницу

            df = df.loc[df['date'] >= cutoff_date]
            fdf = pd.concat([fdf, df], ignore_index=True)
            break

        fdf = pd.concat([fdf, df], ignore_index=True)
        time.sleep(1)

    logger.info(f'Parsed {fdf.shape[0]} records ({cutoff_date} - {date.today()}) from FMP news source')

    return fdf


@asset(group_name='parsing_new_data_experimental')
def news_articles_EOD(tickers_list, cutoff_date) -> pd.DataFrame:
    """
    Gets stock news from [EOD API](https://eodhd.com/financial-apis/stock-market-financial-news-api/)
    :return:
    """

    fdf = pd.DataFrame()

    for ticker in tickers_list.index:
        print(ticker)

        # add country/exchange code
        # Simplified for smaller ticker subset. Will use different exchange encoding logic in prod
        if '.ME' in ticker:  # MOEX
            ticker_ = ticker.replace('.ME', '.MCX')
        elif '.HK' in ticker:  # HSI
            ticker_ = ticker
        else:  # Everything else from tracked ticker subset is from the USA
            ticker_ = f"{ticker}.US"

        for i in range(2, 15):
            url = f"{EOD_HOST}news?s={ticker_}&limit=500&fmt=json&api_token={EOD_KEY}&offset={i*500}"
            try:
                data = requests.get(url, timeout=60).json()
            except Exception as e:
                break

            if not data:
                break

            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date']).dt.date
            df = df.rename(columns={'link': 'url', 'symbols': 'tickersMentioned'})
            df['ticker'] = ticker
            df = df[['date', 'ticker', 'url', 'title', 'content', 'tickersMentioned', 'tags']]

            print(f"{ticker} - {df.shape[0]}")

            if df.date.min() < cutoff_date:
                df = df.loc[df['date'] >= cutoff_date]
                fdf = pd.concat([fdf, df], ignore_index=True)
                break

            fdf = pd.concat([fdf, df], ignore_index=True)
            time.sleep(2)

    return fdf


@asset(group_name='parsing_new_data')
def load_parsed_news_articles(news_articles_FMP):
    """
    Gets new news from API's and combines them into one object
    :return:
    """

    # drop accidental duplicates from merging sources (with priority for EOD)

    # full = pd.concat([news_articles_FMP, news_articles_EOD])
    full = news_articles_FMP[["date", "ticker", "publisher", "url", "title", "content"]]  #, "tickersMentioned", "tags"]]
    # full["tickersMentioned"] = full["tickersMentioned"].astype(str)
    # full["tags"] = full["tags"].astype(str)
    full = full.fillna(np.nan)
    full = full.replace([np.nan], [None])

    with connect(**hse) as con:
        cur = con.cursor()

        cur.executemany("INSERT INTO news.dataset "
                        "(date, ticker, publisher, url, title, content) "  # ", polarity_eod, neg_eod, neu_eod, pos_eod) "
                        "VALUES (%s, %s, %s, %s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE date=VALUES(date)",
                        list(full.itertuples(index=False, name=None)))
        con.commit()
        logger.info(f'Load data query executed, {cur.rowcount} rows affected')
    con.close()
    return 0


if __name__ == '__main__':
    # debug
    ticks = tickers_list()
    eod = news_articles_EOD(ticks, cutoff_date=date(2023, 11, 19))
    fmp = news_articles_FMP(ticks, cutoff_date=date(2023, 11, 19))
    load_parsed_news_articles(fmp)
