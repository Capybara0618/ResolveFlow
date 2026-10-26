import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.apache.rocketmq.client.producer.DefaultMQProducer;
import org.apache.rocketmq.common.message.Message;
import tools.jackson.databind.ObjectMapper;

/** Lab sender: all addresses/groups are explicit; output contains broker acknowledgements. */
public class BackendMqSender {
    public static void main(String[] args) throws Exception {
        if (args.length != 3 || !args[1].matches("127\\.0\\.0\\.1:[0-9]{4,5}")
                || !args[2].matches("rfbe-[a-f0-9]{32}"))
            throw new IllegalArgumentException("explicit owned loopback laboratory required");
        var rows = new ObjectMapper().readTree(Files.readString(Path.of(args[0])));
        if (rows.size() < 1 || rows.size() > 20) throw new IllegalArgumentException("invalid send batch");
        var producer = new DefaultMQProducer(args[2] + "-sender-" + UUID.randomUUID());
        producer.setNamesrvAddr(args[1]);
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
                        if (!go.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("gate timeout");
                        String topic = row.get("topic").stringValue();
                        if (!topic.matches("rf-(case|commerce)-core-v2"))
                            throw new IllegalArgumentException("wrong core topic");
                        var message = new Message(topic, row.get("envelope").stringValue().getBytes(StandardCharsets.UTF_8));
                        message.setKeys(row.get("event_id").stringValue());
                        var result = producer.send(message, 15000);
                        synchronized (System.out) {
                            System.out.println("ACK " + row.get("event_id").stringValue() + " " + result.getSendStatus() + " " + result.getMsgId());
                        }
                        if (!result.getSendStatus().name().equals("SEND_OK"))
                            throw new IllegalStateException("broker did not acknowledge persistence");
                    } catch (Exception e) {
                        throw new RuntimeException(e);
                    }
                }));
            }
            if (!ready.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("sender threads not ready");
            go.countDown();
            for (var job : jobs) job.get(30, TimeUnit.SECONDS);
        } finally {
            producer.shutdown();
        }
    }
}
