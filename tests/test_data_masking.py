from app.utils.data_masking import mask_email, mask_phone, mask_query_rows


def test_contact_masking_formats():
    assert mask_phone("15448401154") == "154****1154"
    assert mask_email("abc@example.com") == "a**@example.com"
    assert mask_email("zhangsan@example.com") == "zha*****@example.com"


def test_query_rows_masks_contact_fields_without_changing_source():
    source = [
        {
            "customer_id": 7,
            "phone": "15448401154",
            "email": "zhangsan@example.com",
            "balance": 12345.67,
        }
    ]

    masked = mask_query_rows(source)

    assert masked == [
        {
            "customer_id": 7,
            "phone": "154****1154",
            "email": "zha*****@example.com",
            "balance": 12345.67,
        }
    ]
    assert source[0]["phone"] == "15448401154"


def test_query_rows_masking_is_idempotent():
    once = mask_query_rows(
        [{"phone": "15448401154", "email": "zhangsan@example.com"}]
    )

    assert mask_query_rows(once) == once
