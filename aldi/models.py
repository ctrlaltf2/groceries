from pydantic import BaseModel
from typing import Any, Self

class SearchAPIResponse(BaseModel):
    class Datum(BaseModel):
        class Price(BaseModel):
            amount: int
            amountRelevant: int
            amountRelevantDisplay: str
            bottleDeposit: int
            bottleDepositDisplay: str
            comparison: int
            comparisonDisplay: Any
            currencyCode: str
            currencySymbol: str
            perUnit: Any
            perUnitDisplay: Any
            wasPriceDisplay: Any
            additionalInfo: Any
            bottleDepositType: Any
            feeText: Any

        class CountryExtensions(BaseModel):
            usSnapEligible: bool

        class Category(BaseModel):
            id: str
            name: str
            urlSlugText: str

        class Asset(BaseModel):
            url: str
            maxWidth: int
            maxHeight: int
            mimeType: str
            assetType: str
            alt: Any
            displayName: Any

        sku: str
        name: str
        brandName: str
        urlSlugText: str
        ageRestriction: Any
        alcohol: Any
        discontinued: bool
        discontinuedNote: Any
        notForSale: bool
        notForSaleReason: Any
        quantityMin: int
        quantityMax: int
        quantityInterval: int
        quantityDefault: int
        quantityUnit: str
        weightType: str
        sellingSize: str
        energyClass: Any
        onSaleDateDisplay: Any
        price: Price
        countryExtensions: CountryExtensions
        categories: list[Category]
        assets: list[Asset]
        badges: list[Any]


    class Meta(BaseModel):
        class Pagination(BaseModel):
            offset: int
            limit: int
            totalCount: int

        class Facet(BaseModel):
            class Config(BaseModel):
                class Component(BaseModel):
                    name: str
                    valueActive: str | None
                    valueInactive: str | None

                parameterName: str
                type: str
                isMultiValue: bool
                componentName: str
                component: Component

            class Value(BaseModel):
                key: str
                docCount: int
                label: str
                isSelected: bool | None
                thumbnail: Any
                children: list[Self]

            name: str
            localizedName: str
            docCount: int
            activeValue: list[Any]
            config: Config
            stats: Any
            values: list[Value]

        class SortItem(BaseModel):
            parameterName: str
            parameterValue: str
            localizedName: str
            isActive: bool

        spellingSuggestion: Any
        pinned: list[Any]
        keywordRedirect: Any
        pagination: Pagination
        debug: Any
        facets: list[Facet]
        sort: list[SortItem]

    meta: Meta
    data: list[Datum]