package ofdkit;

/**
 * 带退出码的受控错误。
 */
class OfdException extends RuntimeException {

    /** 契约退出码：0 成功，2 参数错误，1 运行时错误，3 缺依赖。 */
    final int code;
    final String hint;

    OfdException(int code, String message) {
        this(code, message, null);
    }

    OfdException(int code, String message, String hint) {
        super(message);
        this.code = code;
        this.hint = hint;
    }
}

/**
 * 参数/用法错误（退出码 2）。
 */
class UsageException extends OfdException {
    UsageException(String message) {
        super(2, message);
    }
}
