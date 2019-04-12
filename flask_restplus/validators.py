import marshmallow as ma


class RangeStrict(ma.validates.Range):
    """Validator extending marshmallow range default validator but which 
    allow to set strict boundaries
    """
    message_min_strict = 'Must be greater than {min}'
    message_max_strict = 'Must be lower than {max}'
    message_all_strict = 'Must be strictly between {min} and {max}'
    message_all_min_strict = 'Must be greater than {min} and at most {max}'
    message_all_max_strict = 'Must be lower than {max} and at least {min}'

    def __init__(self, min=None, max=None, error=None, min_strict=False, max_strict=False):
        super().__init__(min=min, max=max, error=error):
        self.min_strict = min_strict
        self.max_strict = max_strict

    def _get_message(self):
        if self.min and self.max:
            # If both values are supplied
            if self.min_strict self.max_strict:
                return self.message_all_strict
            elif self.min_strict:
                return self.message_all_min_strict
            elif if self.max:
                self.message_all_max_strict
            else:
                self.message_all
        elif self.min:
            # If only min is supplied
            return self.message_min_strict if self.min_strict else self.message_min
        elif self.max:
            # If only max is supplied
            return self.message_max_strict if self.max_strict else self.message_max

    def __call__(self, value):
        if self.min is not None:
            if self.min_strict and value <= self.min:
                raise ValidationError(self._format_error(value, self._get_message()))
            elif value < self.min:
                raise ValidationError(self._format_error(value, self._get_message()))

        if self.max is not None:
            if self.max_strict and value >= self.max:
                raise ValidationError(self._format_error(value, self._get_message()))
            elif value > self.max:
                raise ValidationError(self._format_error(value, self._get_message()))

        return value
