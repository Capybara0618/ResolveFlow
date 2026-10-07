import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.ArrayList;
import org.apache.rocketmq.client.producer.DefaultMQProducer;
import org.apache.rocketmq.common.message.Message;
import tools.jackson.databind.ObjectMapper;

/** Local experiment sender: same signed document, explicitly controlled delivery count. */
public class ResumeMqSender {
    public static void main(String[] args) throws Exception {
        var rows = new ObjectMapper().readTree(Files.readString(Path.of(args[0])));
        var producer = new DefaultMQProducer("resume-sender-" + java.util.UUID.randomUUID());
        producer.setNamesrvAddr("127.0.0.1:9879");
        producer.setVipChannelEnabled(false);
        producer.start();
        try (var pool = Executors.newFixedThreadPool(rows.size())) {
            var ready = new CountDownLatch(rows.size());
            var go = new CountDownLatch(1);
            var jobs = new ArrayList<Future<?>>();
            for (var row : rows) {
                jobs.add(pool.submit(() -> {
                    ready.countDown();
                    try {
                        go.await();
                        var msg = new Message(row.get("topic").stringValue(),
                                row.get("envelope").stringValue().getBytes(StandardCharsets.UTF_8));
                        msg.setKeys(row.get("event_id").stringValue());
                        producer.send(msg, 15000);
                    } catch (Exception e) { throw new RuntimeException(e); }
                }));
            }
            ready.await();
            go.countDown();
            for (var job : jobs) job.get();
            System.out.println("SENT " + rows.size());
        } finally { producer.shutdown(); }
    }
}
